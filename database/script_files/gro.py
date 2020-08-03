#!/usr/bin/env python3

import os, sys
import numpy as np
import subprocess 
import multiprocessing as mp
# from multiprocessing import get_context
from shutil import copyfile
from distutils.dir_util import copy_tree
from pathlib import Path
import re
import time
import gen, g_var, at_mod, read_in, at_mod_p


#### collects input structures and creates initial folders
def collect_input():
    if not os.path.exists(g_var.c):
        sys.exit('Cannot find CG input file: '+g_var.c)
    gen.mkdir_directory(g_var.working_dir)
    gen.mkdir_directory(g_var.final_dir)
    gen.mkdir_directory(g_var.input_directory)
    gen.mkdir_directory(g_var.merged_directory)
#### collates all input files in input directory
    if g_var.a != None:
        for file_num, file_name in enumerate(g_var.a):
            if not os.path.exists(file_name):
                sys.exit('cannot find atomistic input file: '+file_name)
            gen.file_copy_and_check(file_name, g_var.input_directory+gen.path_leaf(file_name)[1])
            os.chdir(g_var.input_directory)
            gromacs([g_var.gmx+' editconf -f '+gen.path_leaf(file_name)[1]+' -resnr 0 -o '+g_var.input_directory+'AT_INPUT_'+str(file_num)+'.pdb', g_var.input_directory+'AT_INPUT_'+str(file_num)+'.pdb'])
            if not os.path.exists(g_var.input_directory+'AT_INPUT_'+str(file_num)+'.pdb'):
                sys.exit('\nFailed to process atomistic input file')
            else:
                g_var.user_at_input = True
            os.chdir(g_var.start_dir)

    gen.file_copy_and_check(g_var.c, g_var.input_directory+gen.path_leaf(g_var.c)[1])
    os.chdir(g_var.input_directory)
    gromacs([g_var.gmx+' editconf -f '+gen.path_leaf(g_var.c)[1]+' -resnr 0 -c -o '+g_var.input_directory+'CG_INPUT.pdb', g_var.input_directory+'CG_INPUT.pdb'])
    if not os.path.exists(g_var.input_directory+'CG_INPUT.pdb'):
        sys.exit('\nFailed to process coarsegrain input file')      

#### gromacs parser
def gromacs(gro):
    possible_errors = ['File input/output error:','Error in user input:', 'did not converge to Fmax ', 
                        'but did not reach the requested Fmax ', 'Segmentation fault', 'Fatal error:', 'Cannot read from input']
    cmd,output = gro[0], gro[1]
    error = False
    if os.path.exists(output):
        pass
    else:
    #### if the flag gromacs is used every gromacs command will be printed to the terminal 
        if g_var.v >= 3:
            print('\nrunning gromacs: \n '+cmd+'\n')
        output = subprocess.Popen(cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        # output.wait()
        err, out = output.communicate()
        exitcode = output.returncode
        out=out.decode("utf-8")
    #### all gromacs outputs will be saved into gromacs_outputs within the folder it is run
        with open('gromacs_outputs', 'a') as checks:
            checks.write(out)
    #### standard catch for failed gromacs commands
            for err in possible_errors:
                if err in out:
                    print('\n'+out)
                    if 'residue naming needs to be fixed' in out and 'PROTEIN_aligned' in out:
                        print('\n\n###  The supplied protein structure contains incorrectly named or missing atoms  ###\n\n')
                    error = True
            if 'number of atoms in the topology (' in out:
                print('\n'+out+'\n\n')
                print('{0:^90}\n\n{1:^90}\n'.format('***NOTE***','If it is only out by multiples of two, check cysteine distances and increase -cys cutoff'))
                print('{0:^90}\n\n'.format('A lot of Martini v2-2 disulphide bonds can be up to 10 A (current search cutoff is '+str(g_var.cys)+' A)')) 
                error = True
            if  'Warning: pressure scaling more than 1%' in out:
                print('pressure coupling failed trying Berendsen instead')
                error = True
    if len(gro) == 4: 
        gro[3].put(gro[2])
        return gro[2], error 
    return 0, error

def make_min(residue):#, fragments):
#### makes minimisation folder
    gen.mkdir_directory('MIN')
#### makes em.mdp file for each residue
    if not os.path.exists('em_'+residue+'.mdp'):
        with open('em_'+residue+'.mdp','w') as em:
            em.write('define = \n integrator = steep\nnsteps = 20000\nemtol = 750\nemstep = 0.001\ncutoff-scheme = Verlet\n')

def pdb2gmx_minimise(chain,pdb2gmx_selections,res_type, q):
    os.chdir(g_var.working_dir+'/'+res_type)
    if not os.path.exists(res_type+'_de_novo_'+str(chain)+'_gmx.pdb'):
        pdb2gmx_chain(chain, 'de_novo_', res_type, ' << EOF \n1\n'+str(pdb2gmx_selections[chain][0])+'\n'+str(pdb2gmx_selections[chain][1]))
    if not os.path.exists(res_type+'_de_novo_'+str(chain)+'_gmx_checked.pdb'):
        at_mod.check_overlap_chain(chain, 'de_novo_', res_type)
    if g_var.user_at_input and not os.path.exists(res_type+'_aligned_'+str(chain)+'_gmx_checked.pdb') and res_type == 'PROTEIN':
        pdb2gmx_selections[chain] = histidine_protonation(chain, 'de_novo_', pdb2gmx_selections[chain])
        pdb2gmx_chain(chain, 'aligned_', res_type, pdb2gmx_selections[chain])
        at_mod.check_overlap_chain(chain, 'aligned_', res_type)
    minimise_protein_chain(chain, 'de_novo_', res_type)
    if g_var.user_at_input and res_type == 'PROTEIN': 
        minimise_protein_chain(chain, 'aligned_', res_type)
    q.put(chain)
    return chain


def histidine_protonation(chain, input, chain_ter):
#### reads protonation state of histidine from itp file
    histidines=[]
    with open('PROTEIN_'+input+str(chain)+'.top', 'r') as top_input:
        for line in top_input.readlines():
            if line.startswith('; residue'):
                if line.split()[5] in ['HSD','HID']:
                    histidines.append(0)
                elif line.split()[5] in ['HSE', 'HIE']:
                    histidines.append(1)
                elif line.split()[5] in ['HSP','HIS1']:
                    histidines.append(2)
    pdb2gmx_selections='-his << EOF \n1'
    for his in histidines:
        pdb2gmx_selections+='\n'+str(his)
    pdb2gmx_selections+='\n'+str(chain_ter[0])+'\n'+str(chain_ter[1])
    return pdb2gmx_selections


### interactive terminal residue selection
def ask_ter_question(residue, options, chain):
    print('\n please select species for '+residue+' residue in chain '+str(chain))
    print('\nPlease select a option from below:\n')
    print('{0:^20}{1:^30}'.format('Selection','termini'))
    print('{0:^20}{1:^30}'.format('---------','----------'))
    sel=[]
    for selection, ter in enumerate(options):
        sel.append(ter)
        print('{0:^20}{1:^30}'.format(selection,ter))
    while True:
        try:
            number = int(input('\nplease select a option: '))
            if number < len(options):
                return options[sel[number]]
        except KeyboardInterrupt:
            sys.exit('\nInterrupted')
        except:
            print("Oops!  That was a invalid choice")

def ask_terminal(sys_info, residue_type):
#### default termini is neutral, however if ter flag is supplied you interactively choose termini ]
    for ff in g_var.termini_selections:
        if ff in g_var.forcefield:
            ter_conv = g_var.termini_selections[ff]

    system_ter = []
    for chain in range(g_var.system[residue_type]):
        conv_type = 'NORM'
        default_ter=[]
        ter_name=['N_TERMINAL','C_TERMINAL']
        for ter_val,  ter_residue in enumerate(sys_info[chain]):
            if ter_residue == 'PRO' and ter_val == 0:
                conv_type = 'PRO'
            termini = g_var.res_top[ter_residue][ter_name[ter_val]]
            if len(termini) == 0:
                if g_var.nt and ter_val==0 and not g_var.ter:
                    if conv_type == 'PRO':
                        default_ter.append(ter_conv[ter_name[ter_val]][conv_type]['NH'])
                    else:
                        default_ter.append(ter_conv[ter_name[ter_val]][conv_type]['NH2'])
                elif ter_val==0 and not g_var.ter:
                    default_ter.append(ter_conv[ter_name[ter_val]][conv_type]['NH3+'])
                if g_var.ct and ter_val==1 and not g_var.ter:
                    default_ter.append(ter_conv[ter_name[ter_val]][conv_type]['COOH'])
                elif ter_val==1 and not g_var.ter:
                    default_ter.append(ter_conv[ter_name[ter_val]][conv_type]['COO-'])
                if g_var.ter:
                    default_ter.append(ask_ter_question(termini, ter_conv[ter_name[ter_val]][conv_type], chain))
            else:
                default_ter.append(ter_conv[ter_name[ter_val]][conv_type][termini])
                if g_var.ter:
                    print('\n The '+ter_name[ter_val]+' of residue '+ter_residue+' is non adjustable')
        system_ter.append(default_ter)
    return system_ter

def run_parallel_pdb2gmx_min(res_type, sys_info):
    pool = mp.Pool(g_var.ncpus)
    m = mp.Manager()
    q = m.Queue()
    os.chdir(g_var.working_dir+res_type)
    make_min(res_type)
    gen.folder_copy_and_check(g_var.forcefield_location+g_var.forcefield, g_var.working_dir+res_type+'/'+g_var.forcefield+'/.')
    gen.file_copy_and_check(g_var.forcefield_location+'/residuetypes.dat', g_var.working_dir+res_type+'/residuetypes.dat')
    pdb2gmx_selections=ask_terminal(sys_info, res_type)
    pool_process = pool.starmap(pdb2gmx_minimise, [(chain, pdb2gmx_selections,res_type, q) for chain in range(0, g_var.system[res_type])])
    while len(pool_process) != g_var.system[res_type]:
        report_complete('pdb2gmx/minimisation', q.qsize(), g_var.system[res_type])
    print('{:<130}'.format(''), end='\r')
    print('pdb2gmx/minimisation completed on residue type: '+res_type)     
    pool.close()
    pool.join()

def pdb2gmx_chain(chain, input,res_type, pdb2gmx_selections):
#### pdb2gmx on on protein chain, creates the topologies    
    out, err = gromacs([g_var.gmx+' pdb2gmx -f '+res_type+'_'+input+str(chain)+'.pdb -o '+res_type+'_'+input+str(chain)+'_gmx.pdb -water none \
    -p '+res_type+'_'+input+str(chain)+'.top  -i '+res_type+'_'+str(chain)+'_posre.itp '+g_var.vs+' -ter '+pdb2gmx_selections+'\nEOF', ''+res_type+'_'+input+str(chain)+'_gmx.pdb']) #### single chains
#### converts the topology file and processes it into a itp file
    convert_topology(res_type+'_'+input, chain, res_type)
#### writes topology overview for each chain 
    write_topol(res_type+'_'+input, 1, str(chain))
#### writes restraints file for each chain
    if res_type == 'PROTEIN':
        write_posres(chain)

def minimise_protein_chain(chain, input, res_type):
    #### grompps each protein chain
    gromacs([g_var.gmx+' grompp '+
                '-f em_'+res_type+'.mdp '+
                '-p topol_'+res_type+'_'+input+str(chain)+'.top '+
                '-c '+res_type+'_'+input+str(chain)+'_gmx_checked.pdb '+
                '-o MIN/'+res_type+'_'+input+str(chain)+' '+
                '-maxwarn 1 ', 'MIN/'+res_type+'_'+input+str(chain)+'.tpr'])
#### minimises chain
    os.chdir('MIN')
    gromacs([g_var.gmx+' mdrun -v -nt 1 -deffnm '+res_type+'_'+input+str(chain)+' -c '+res_type+'_'+input+str(chain)+'.pdb', ''+res_type+'_'+input+str(chain)+'.pdb'])
    os.chdir('..')  


def posres_header(file_write):
        posres_output = open(file_write, 'w')
        posres_output.write('[ position_restraints ]\n; atom  type      fx      fy      fz\n')
        return posres_output

def write_posres(chain):
#### if not posres file exist create one
    steered_posres = posres_header(g_var.working_dir+'PROTEIN/PROTEIN_'+str(chain)+'_steered_posre.itp')
    very_low_posres = posres_header(g_var.working_dir+'PROTEIN/PROTEIN_'+str(chain)+'_very_low_posre.itp')
    low_posres = posres_header(g_var.working_dir+'PROTEIN/PROTEIN_'+str(chain)+'_low_posre.itp')
    mid_posres = posres_header(g_var.working_dir+'PROTEIN/PROTEIN_'+str(chain)+'_mid_posre.itp')
    high_posres = posres_header(g_var.working_dir+'PROTEIN/PROTEIN_'+str(chain)+'_high_posre.itp')
    very_high_posres = posres_header(g_var.working_dir+'PROTEIN/PROTEIN_'+str(chain)+'_very_high_posre.itp')
    ultra_posres = posres_header(g_var.working_dir+'PROTEIN/PROTEIN_'+str(chain)+'_ultra_posre.itp')
    ca_posres = posres_header(g_var.working_dir+'PROTEIN/PROTEIN_'+str(chain)+'_ca_posre.itp')
    #### read in each chain from after pdb2gmx 
    with open(g_var.working_dir+'PROTEIN/PROTEIN_de_novo_'+str(chain)+'_gmx.pdb', 'r') as pdb_input:
        at_counter=0
        for line in pdb_input.readlines():
            if line.startswith('ATOM'):
                line_sep = gen.pdbatom(line)
                at_counter+=1
            #### if atom is in the restraint list for that residue add to position restraint file
                if line_sep['atom_name'] == 'CA':
                    ca_posres.write(str(at_counter)+'     1  100  100  100\n')
                if not gen.is_hydrogen(line_sep['atom_name']):
                    very_low_posres.write(str(at_counter)+'     1  200  200  200\n')
                    low_posres.write(str(at_counter)+'     1  750  750  750\n')
                    mid_posres.write(str(at_counter)+'     1  1500  1500  1500\n')
                    high_posres.write(str(at_counter)+'     1  3000  3000  3000\n')
                    very_high_posres.write(str(at_counter)+'     1  6000  6000  6000\n')
                    ultra_posres.write(str(at_counter)+'     1  10000  10000  10000\n')

def convert_topology(topol, protein_number, res_type):
#### reads in topology 
    if Path(topol+str(protein_number)+'.top').exists():
        read=False
        mol_type=False
        if not os.path.exists(topol+str(protein_number)+'.itp'):
            with open(topol+str(protein_number)+'.itp', 'w') as itp_write:

                for line in open(topol+str(protein_number)+'.top', 'r').readlines():
                    # print(line)
                #### copies between moleculetype and position restraint section
                    if len(line.split()) > 1: 
                        if read == False and line.split()[1] == 'moleculetype':
                            read = True
                        if line.split()[0]== '[' and line.split()[1] == 'moleculetype' and read:
                            mol_type = True
                        elif line.split()[0]== '[' and line.split()[1] == 'atoms' and read:
                            mol_type = False
                        elif mol_type:
                            if not line.startswith(';'):
                                line = '{0}       {1:20}'.format(res_type.lower()+'_'+str(protein_number), line.split()[1])
                        if read == True and line.split()[1] == 'POSRES':
                            read = False
                #### writes to itp file copied section          
                    if read:
                        # print(line)
                        itp_write.write(line)
                if res_type in ['PROTEIN']:
                #### adds position restraint section to end of itp file         
                    itp_write.write('#ifdef POSRES\n#include \"'+res_type+'_'+str(protein_number)+'_posre.itp\"\n#endif\n') 
                    itp_write.write('#ifdef POSRESCA\n#include \"'+res_type+'_'+str(protein_number)+'_ca_posre.itp\"\n#endif\n') 
                    itp_write.write('#ifdef VERY_LOWPOSRES\n#include \"'+res_type+'_'+str(protein_number)+'_very_low_posre.itp\"\n#endif\n')
                    itp_write.write('#ifdef LOWPOSRES\n#include \"'+res_type+'_'+str(protein_number)+'_low_posre.itp\"\n#endif\n')
                    itp_write.write('#ifdef MIDPOSRES\n#include \"'+res_type+'_'+str(protein_number)+'_mid_posre.itp\"\n#endif\n')
                    itp_write.write('#ifdef HIGHPOSRES\n#include \"'+res_type+'_'+str(protein_number)+'_high_posre.itp\"\n#endif\n')
                    itp_write.write('#ifdef VERY_HIGHPOSRES\n#include \"'+res_type+'_'+str(protein_number)+'_very_high_posre.itp\"\n#endif\n')
                    itp_write.write('#ifdef ULTRAPOSRES\n#include \"'+res_type+'_'+str(protein_number)+'_ultra_posre.itp\"\n#endif\n')
                    itp_write.write('#ifdef POSRES_STEERED\n#include \"'+res_type+'_'+str(protein_number)+'_steered_posre.itp\"\n#endif\n')
    else:
        sys.exit('cannot find : '+topol+'_'+str(protein_number)+'.top')

def write_topol(residue_type, residue_number, chain):
#### open topology file
    found=False
    with open('topol_'+residue_type+chain+'.top', 'w') as topol_write:
    #### add standard headers may need to be changed dependant on forcefield
        topol_write.write('; Include forcefield parameters\n#include \"'+g_var.final_dir+g_var.forcefield+'/forcefield.itp\"\n')
        if 'SOL' == residue_type:
            topol_write.write('#include \"'+g_var.water_dir+g_var.water+'.itp\"\n\n#include \"'+g_var.final_dir+g_var.forcefield+'/ions.itp\"\n\n')
    #### add location of residue topology file absolute file locations
        if residue_type not in ['ION','SOL']:
            for directory in range(len(g_var.np_directories)):
                if os.path.exists(g_var.np_directories[directory][0]+residue_type+'/'+residue_type+'.itp'):
                    topol_write.write('#include \"'+g_var.np_directories[directory][0]+residue_type+'/'+residue_type+'.itp\"\n')
                    found=True
                    break
            if os.path.exists(g_var.working_dir+'/'+residue_type.split('_')[0]+'/'+residue_type+chain+'.itp'):
                topol_write.write('#include \"'+residue_type+chain+'.itp\"\n')
                found=True
            if not found:
                sys.exit('cannot find itp : '+residue_type+'/'+residue_type+chain)
    #### topology section headers
        topol_write.write('\n\n[ system ]\n; Name\nSomething clever....\n\n[ molecules ]\n; Compound        #mols\n')
    #### individual number of residues
        if residue_type.split('_')[0] in ['PROTEIN', 'OTHER']:
             residue_type=residue_type.split('_')[0]+'_'
        topol_write.write(residue_type+chain+'    '+str(residue_number))


#################################################################   Non protein

def non_protein_minimise_ind(residue_type):
#### in the case of SOL all residues are minimised, whilst in all other cases individual residues are minimised separately
    if residue_type != 'SOL':
        individual = 1
        resid=g_var.system[residue_type]
    else:
        individual=g_var.system['SOL']
        resid=1
    os.chdir(g_var.working_dir+residue_type)
### write topology and minimisation parts (min folder and em.mdp)
    write_topol(residue_type, individual, '')
    make_min(residue_type)#, fragment_names)
#### spin up multiprocessing for grompp 
    pool = mp.Pool(g_var.ncpus)
    m = mp.Manager()
    q = m.Queue()
    pool_process = pool.map_async(gromacs, [(g_var.gmx+' grompp '+
                                  '-po md_out-'+residue_type+'_temp_'+str(rid)+' '+
                                  '-f em_'+residue_type+'.mdp '+
                                  '-p topol_'+residue_type+'.top '+
                                  '-c '+residue_type+'_'+str(rid)+'.pdb '+
                                  '-o MIN/'+residue_type+'_temp_'+str(rid)+' -maxwarn 1', 
                                  'MIN/'+residue_type+'_temp_'+str(rid)+'.tpr',rid, q) for rid in range(0, resid)])
    while not pool_process.ready():
        report_complete('GROMPP', q.qsize(), resid)
    print('{:<100}'.format(''), end='\r')
    print('GROMPP completed on residue type: '+residue_type)       
    pool.close()
#### close grompp multiprocessing and change to min directory and spin up mdrun multiprocessing
    os.chdir('MIN')
    m = mp.Manager()
    q = m.Queue()
    pool = mp.Pool(g_var.ncpus)
    pool_process = pool.map_async(gromacs, [(g_var.gmx+' mdrun -v -nt 1 -deffnm '+residue_type+'_temp_'+str(rid)+' -c '+residue_type+'_'+str(rid)+'.pdb', 
                                  residue_type+'_'+str(rid)+'.pdb',rid, q) for rid in range(0, resid)])          ## minimisation grompp parallised  
    while not pool_process.ready():
        report_complete('Minimisation', q.qsize(), resid)
    print('                                                                       ', end='\r')
    print('Minimisation completed on residue type: '+residue_type)
    pool.close()
    os.chdir(g_var.working_dir)

def report_complete(func, size, resid):
    print('{:<100}'.format(''), end='\r')
    print('Running '+func+' on '+str(resid)+' residues: percentage complete: ',np.round((size/resid)*100,2),'%', end='\r')
    time.sleep(0.1)

def minimise_merged(residue_type, input_file):
#### write topology for merged system    
    os.chdir(g_var.working_dir+residue_type)
    make_min(residue_type)
    write_topol(residue_type, g_var.system[residue_type], '')
#### grompp with merged system
    gromacs([g_var.gmx+' grompp '+
            '-po md_out-'+residue_type+' '+
            '-f em_'+residue_type+'.mdp '+
            '-p topol_'+residue_type+'.top '+
            '-c '+input_file+' '+
            '-o '+g_var.working_dir+residue_type+'/MIN/'+residue_type+'_merged_min -maxwarn 1', g_var.working_dir+residue_type+'/MIN/'+residue_type+'_merged_min.tpr'])
#### change to min directory and minimise
    os.chdir('MIN') 
    complete, success = gromacs([g_var.gmx+' mdrun -v -nt '+str(g_var.ncpus)+' -pin on -deffnm '+residue_type+'_merged_min -c ../'+residue_type+'_merged.pdb', '../'+residue_type+'_merged.pdb'])
    os.chdir(g_var.working_dir)
    return success



################################################################ Gromacs for merged system

def check_atom_type(line, a_line, atomtypes_itp_lines):
    line_sep=line.split() 
    name = int(np.where(line_sep[0]==a_line[:,0])[0])  
    bond = int(np.where(line_sep[1]==a_line[:,1])[0]) 
    if name == bond: 
        if float(line_sep[5]) != float(a_line[name][5]) or float(line_sep[6]) != float(a_line[name][6]): 
            sys.exit('\nThere are duplicate atomtypes in your molecules: \n'+line) 

def strip_atomtypes(itp_file): 
    with open(itp_file, 'r') as itp_input: 
        itp_lines = itp_input.read().splitlines() 
    atom_types=[] 
    if '[ atomtypes ]' in itp_lines: 
        a_lines_sep = []
        if not os.path.exists('extra_atomtypes.itp'): 
            atomtypes_output = open('extra_atomtypes.itp', 'w') 
            atomtypes_output.write('[ atomtypes ]\n') 
        else: 
            atomtypes_output = open('extra_atomtypes.itp', 'a') 
            with open('extra_atomtypes.itp', 'r') as atomtypes_itp_r: 
                atomtypes_itp_lines = atomtypes_itp_r.read().splitlines() 
            for a_line in atomtypes_itp_lines[1:]: 
                if not a_line.startswith(';'):  
                    a_lines_sep.append(a_line.split()) 
            a_lines_sep = np.array(a_lines_sep) 
        atom = itp_lines.index('[ atomtypes ]')+1 
        mol = itp_lines.index('[ moleculetype ]') 
        for line in itp_lines[atom:mol]: 
            if not line.startswith(';'): 
                line_sep = line.split() 
                if len(line_sep) > 4: 
                    if len(a_lines_sep) > 2:
                        if line_sep[0] not in a_lines_sep[:,0] and line_sep[1] not in a_lines_sep[:,1]: 
                            atomtypes_output.write(line+'\n') 
                        else: 
                            check_atom_type(line, a_lines_sep, atomtypes_itp_lines) 
                    else:
                        atomtypes_output.write(line+'\n')
        with open(itp_file, 'w') as itp_output: 
            for line in itp_lines[mol:]: 
                itp_output.write(line+'\n')

def write_merged_topol():
    os.chdir(g_var.working_dir+'MERGED')
    # if not os.path.exists('topol_final.top'):
    with open('topol_final.top', 'w') as topol_write:
        topologies_to_include=[]
    #### writes topology headers (will probably need updating with other forcefields)
        if 'SOL' in g_var.system:
            gen.file_copy_and_check(g_var.water_dir+g_var.water+'.itp', g_var.water+'.itp')
            topologies_to_include.append('#include \"'+g_var.water+'.itp\"')
            topologies_to_include.append('\n#include \"'+g_var.final_dir+g_var.forcefield+'/ions.itp\"\n\n')
    #### runs through residue types and copies to MERGED directory and simplifies the names
        for residue_type in g_var.system:
            if residue_type not in ['ION','SOL']:
            #### copies 1st itp file it comes across 
                for directory in g_var.np_directories:
                    if os.path.exists(directory[0]+residue_type+'/'+residue_type+'.itp'):  
                        topologies_to_include.append('#include \"'+residue_type+'.itp\"\n')
                        gen.file_copy_and_check(directory[0]+residue_type+'/'+residue_type+'.itp', residue_type+'.itp')
                        gen.file_copy_and_check(directory[0]+residue_type+'/'+residue_type+'_posre.itp', residue_type+'_posre.itp')
                        strip_atomtypes(residue_type+'.itp')
                        break
            #### copies across protein itp files and simplifies the names 
                if residue_type in ['PROTEIN', 'OTHER']:
                    for unit in range(g_var.system[residue_type]): 
                        topologies_to_include.append('#include \"'+residue_type+'_'+str(unit)+'.itp\"\n')
                        gen.file_copy_and_check(g_var.working_dir+residue_type+'/'+residue_type+'_de_novo_'+str(unit)+'.itp', residue_type+'_'+str(unit)+'.itp')
                        if residue_type in ['PROTEIN']:
                            for posres_type in ['_steered_posre.itp','_very_low_posre.itp','_low_posre.itp','_mid_posre.itp','_high_posre.itp','_very_high_posre.itp','_ultra_posre.itp','_ca_posre.itp','_posre.itp']:
                                gen.file_copy_and_check(g_var.working_dir+'PROTEIN/PROTEIN_'+str(unit)+posres_type, 'PROTEIN_'+str(unit)+posres_type)
                            gen.file_copy_and_check(g_var.working_dir+'PROTEIN/PROTEIN_disres.itp', 'PROTEIN_disres.itp')  
        if os.path.exists('extra_atomtypes.itp'):
            topol_write.write('; Include forcefield parameters\n#include \"'+g_var.final_dir+g_var.forcefield+'/forcefield.itp\"\n')
            topol_write.write('#include \"extra_atomtypes.itp\"\n')
        else:
            topol_write.write('; Include forcefield parameters\n#include \"'+g_var.final_dir+g_var.forcefield+'/forcefield.itp\"\n')
        for line in topologies_to_include:
            topol_write.write(line)

        topol_write.write('[ system ]\n; Name\nSomething clever....\n\n[ molecules ]\n; Compound        #mols\n')
    #### adds number of residues to the topology
        for residue_type in g_var.system:
            if residue_type not in  ['PROTEIN', 'OTHER']:
                topol_write.write(residue_type+'    '+str(g_var.system[residue_type])+'\n')   
        #### adds monomers separately
            else:
                for unit in range(g_var.system[residue_type]):
                    topol_write.write(residue_type+'_'+str(unit)+'    1\n')    
        topol_write.write('\n#ifdef DISRES\n#include \"PROTEIN_disres.itp\"\n#endif')


def minimise_merged_pdbs(protein):
    print('\nMinimising merged atomistic files : '+protein[1:])
    os.chdir(g_var.working_dir+'MERGED')
#### grompps final merged systems
    gromacs([g_var.gmx+' grompp '+
            '-po md_out-merged_cg2at '+
            '-f em_merged_cg2at.mdp '+
            '-p topol_final.top '+
            '-r merged_cg2at'+protein+'.pdb '+
            '-c merged_cg2at'+protein+'.pdb '+
            '-o MIN/merged_cg2at'+protein+'_minimised '+
            '-maxwarn 1', 'MIN/merged_cg2at'+protein+'_minimised.tpr'])
    os.chdir('MIN')
#### runs minimises final systems
    gromacs([g_var.gmx+' mdrun -nt '+str(g_var.ncpus)+' -v -pin on -deffnm merged_cg2at'+protein+'_minimised -c merged_cg2at'+protein+'_minimised.pdb', 'merged_cg2at'+protein+'_minimised.pdb'])


def alchembed():
    os.chdir(g_var.working_dir+'MERGED')
    gen.mkdir_directory('ALCHEMBED')
#### runs through each chain and run alchembed on each sequentially
    for chain in range(g_var.system['PROTEIN']):
        print('Running alchembed on chain: '+str(chain))
    #### creates a alchembed mdp for each chain 
        if not os.path.exists('alchembed_'+str(chain)+'.mdp'):
            with open('alchembed_'+str(chain)+'.mdp', 'w') as alchembed:
                alchembed.write('define = -DPOSRES\nintegrator = sd\nnsteps = 500\ndt = 0.001\ncontinuation = no\nconstraint_algorithm = lincs')
                alchembed.write('\nconstraints = all-bonds\nns_type = grid\nnstlist = 25\nrlist = 1\nrcoulomb = 1\nrvdw = 1\ncoulombtype  = PME')
                alchembed.write('\npme_order = 4\nfourierspacing = 0.16\ntc-grps = system\ntau_t = 0.1\nref_t = 310\ncutoff-scheme = Verlet')
                alchembed.write('\npcoupl = no\n')
                alchembed.write('\npbc = xyz\nDispCorr = no\ngen_vel = yes\ngen_temp = 310\ngen_seed = -1\nfree_energy = yes\ninit_lambda = 0.00')
                alchembed.write('\ndelta_lambda = 1e-3\nsc-alpha = 0.1000\nsc-power = 1\nsc-r-power = 6\ncouple-moltype = protein_'+str(chain))
                alchembed.write('\ncouple-lambda0 = none\ncouple-lambda1 = vdw\nrefcoord_scaling = all')
    #### if 1st chain use minimised structure for coordinate input
        if chain == 0:
            gromacs([g_var.gmx+' grompp '+
                    '-po md_out-merged_cg2at_alchembed_'+str(chain)+' '+
                    '-f alchembed_'+str(chain)+'.mdp '+
                    '-p topol_final.top '+
                    '-r MIN/merged_cg2at_de_novo_minimised.pdb '+
                    '-c MIN/merged_cg2at_de_novo_minimised.pdb '+
                    '-o ALCHEMBED/merged_cg2at_de_novo_supplied_alchembed_'+str(chain)+' '+
                    '-maxwarn 1', 'ALCHEMBED/merged_cg2at_de_novo_supplied_alchembed_'+str(chain)+'.tpr'])
    #### if not 1st chain use the previous output of alchembed tfor the input of the next chain 
        else:
            gromacs([g_var.gmx+' grompp '+
                '-po md_out-merged_cg2at_alchembed_'+str(chain)+' '+
                '-f alchembed_'+str(chain)+'.mdp '+
                '-p topol_final.top '+
                '-r MIN/merged_cg2at_de_novo_minimised.pdb '+
                '-c ALCHEMBED/merged_cg2at_de_novo_supplied_alchembed_'+str(chain-1)+'.pdb '+
                '-o ALCHEMBED/merged_cg2at_de_novo_supplied_alchembed_'+str(chain)+' '+
                '-maxwarn 1', 'ALCHEMBED/merged_cg2at_de_novo_supplied_alchembed_'+str(chain)+'.tpr'])          
        os.chdir('ALCHEMBED')
    #### run alchembed on the chain of interest
        gromacs([g_var.gmx+' mdrun -nt '+str(g_var.ncpus)+' -v -pin on -deffnm merged_cg2at_de_novo_supplied_alchembed_'+str(chain)+
                ' -c merged_cg2at_de_novo_supplied_alchembed_'+str(chain)+'.pdb', 'merged_cg2at_de_novo_supplied_alchembed_'+str(chain)+'.pdb'])
        os.chdir('..')
#### copy final output to the FINAL folder
    gen.file_copy_and_check('ALCHEMBED/merged_cg2at_de_novo_supplied_alchembed_'+str(chain)+'.pdb', g_var.merged_directory+'checked_ringed_lipid_de_novo.pdb')
    if len(at_mod.check_ringed_lipids(g_var.merged_directory+'checked_ringed_lipid_de_novo.pdb')) > 0: ## rechecks for abnormal bond lengths
        print('Check final output as alchembed cannot fix ringed lipid: ', ringed_lipids) ## warning that the script failed to fix bonds
    
def write_steered_mdp(loc, posres, time, timestep):
    if not os.path.exists(loc):
        with open(loc, 'w') as steered_md:
            steered_md.write('define = '+posres+'\nintegrator = md\nnsteps = '+str(time)+'\ndt = '+str(timestep)+'\ncontinuation   = no\nconstraint_algorithm = lincs\n')
            steered_md.write('nstxtcout = 10\nnstenergy = 10\nconstraints = all-bonds\nns_type = grid\nnstlist = 25\nrlist = 1.2\nrcoulomb = 1.2\nrvdw = 1.2\ncoulombtype  = PME\n')
            steered_md.write('pme_order = 4\nfourierspacing = 0.135\ntcoupl = v-rescale\ntc-grps = system\ntau_t = 0.1\nref_t = 310\npcoupl = no\n')
            steered_md.write('pbc = xyz\nDispCorr = no\ngen_vel = no\nrefcoord_scaling = all\ncutoff-scheme = Verlet\ndisre=simple\ndisre-weighting=equal\ndisre-fc=10000\ndisre-tau=0')   

def steer_to_aligned(protein_type, fc, input_file ):
    gen.mkdir_directory(g_var.merged_directory+'STEER')
    print('Applying '+fc.replace('_',' ')+' position restraints', end='\r')
    os.chdir(g_var.merged_directory)
    write_steered_mdp(g_var.merged_directory+fc+'_posres-nvt.mdp', '-D'+fc.upper()+'POSRES -DNP', 2000, 0.001)  
    gromacs([g_var.gmx+' grompp '+
            ' -po md_out-merged_cg2at_steer_'+fc+
            ' -f '+fc+'_posres-nvt.mdp '+
            ' -p topol_final.top '+
            ' -r merged_cg2at_'+protein_type+'.pdb '+
            ' -c '+input_file+'.pdb '+
            ' -o STEER/merged_cg2at_'+protein_type+'_steer_'+fc+' '+
            ' -maxwarn '+str(2), 'STEER/merged_cg2at_'+protein_type+'_steer_'+fc+'.tpr'])  
    os.chdir('STEER')
    complete, equil = gromacs([g_var.gmx+' mdrun -v -nt '+str(g_var.ncpus)+' -pin on -deffnm merged_cg2at_'+protein_type+'_steer_'+fc+
                                 ' -c merged_cg2at_'+protein_type+'_steer_'+fc+'.pdb -cpo merged_cg2at_'+protein_type+'_steer_'+fc+'.cpt'
                                 ,'merged_cg2at_'+protein_type+'_steer_'+fc+'.pdb'])
    print('{:<100}'.format(''), end='\r')
    return equil


def run_nvt(input_file):
    print('Running NVT on de novo system')
    os.chdir(g_var.merged_directory)   
    gen.mkdir_directory(g_var.merged_directory+'NVT')
    if g_var.user_at_input and g_var.disre:
        write_steered_mdp(g_var.merged_directory+'nvt.mdp', '-DDISRES -DPOSRESCA', 5000, 0.001)
    else:
        write_steered_mdp(g_var.merged_directory+'nvt.mdp', '-DPOSRESCA', 5000, 0.001)
    gromacs([g_var.gmx+' grompp'+
            ' -po md_out-merged_cg2at_npt'+
            ' -f nvt.mdp'+
            ' -p topol_final.top'+
            ' -r '+input_file+'.pdb '+
            ' -c '+input_file+'.pdb '+
            ' -o NVT/merged_cg2at_de_novo_nvt'+
            ' -maxwarn '+str(2), 'NVT/merged_cg2at_de_novo_nvt.tpr'])   
    os.chdir(g_var.merged_directory+'NVT')
    gromacs([g_var.gmx+' mdrun -v -nt '+str(g_var.ncpus)+' -pin on -deffnm merged_cg2at_de_novo_nvt'+
            ' -c merged_cg2at_de_novo_nvt.pdb -cpo merged_cg2at_de_novo_nvt.cpt'
            , 'merged_cg2at_de_novo_nvt.pdb'])  
    gen.file_copy_and_check('merged_cg2at_de_novo_nvt.pdb', g_var.final_dir+'final_cg2at_de_novo.pdb')    

def create_aligned():
    print('\nCreating aligned system') 
    at_mod.merge_system_pdbs('_aligned') ## create restraint positions for aligned system
    aligned_atoms, chain_count = read_in.read_in_atomistic(g_var.working_dir+'PROTEIN/PROTEIN_aligned_merged.pdb') ## reads in final pdb
    rmsd = at_mod_p.RMSD_measure(aligned_atoms) ## gets rmsd of de novo
    if os.path.exists(g_var.final_dir+'final_cg2at_de_novo.pdb'):
        initial = g_var.final_dir+'final_cg2at_de_novo'
    else:
        initial = g_var.merged_directory+'checked_ringed_lipid_de_novo'
    for chain in rmsd:
        if rmsd[chain] > 2:
            print('Your aligned structure is quite far from the CG, therefore running gentle steering')
            steer = ['very_low', 'low', 'mid', 'high', 'very_high', 'ultra']
            break
        else:
            steer = ['low', 'high', 'ultra']


    for res_val, restraint in enumerate(steer):
        if not os.path.exists(g_var.merged_directory+'STEER/merged_cg2at_aligned_steer_'+restraint+'pdb'):
            
            if res_val == 0:
                equil = steer_to_aligned('aligned', restraint, initial)
            else:
                equil = steer_to_aligned('aligned', restraint, g_var.merged_directory+'STEER/merged_cg2at_aligned_steer_'+steer[res_val-1])
            if equil:
                print('Steering to aligned failed at: '+restraint)
                print('Your aligned structure may be too far from the CG input')
                print('The closest the script can get is found in the FINAL directory')
                gen.file_copy_and_check(g_var.merged_directory+'STEER/merged_cg2at_aligned_steer_'+restraint+'pdb', g_var.final_dir+'final_cg2at_aligned.pdb') ## copy to final folder
    gen.file_copy_and_check(g_var.merged_directory+'STEER/merged_cg2at_aligned_steer_'+steer[-1]+'.pdb', g_var.final_dir+'final_cg2at_aligned.pdb') ## copy to final folder
    print()