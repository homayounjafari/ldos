#
# PAOFLOW
#
# Utility to construct and operate on Hamiltonians from the Projections of DFT wfc on Atomic Orbital bases (PAO)
#
# Copyright (C) 2016-2018 ERMES group (http://ermes.unt.edu, mbn@unt.edu)
#
# Reference:
# M. Buongiorno Nardelli, F. T. Cerasoli, M. Costa, S Curtarolo,R. De Gennaro, M. Fornari, L. Liyanage, A. Supka and H. Wang,
# PAOFLOW: A utility to construct and operate on ab initio Hamiltonians from the Projections of electronic wavefunctions on
# Atomic Orbital bases, including characterization of topological materials, Comp. Mat. Sci. vol. 143, 462 (2018).
#
# This file is distributed under the terms of the
# GNU General Public License. See the file `License'
# in the root directory of the present distribution,
# or http://www.gnu.org/copyleft/gpl.txt .
#

import numpy as np
from mpi4py import MPI

from .do_atwfc_proj import *
from .write2xsf import write2xsf
from .communication import load_balancing

comm = MPI.COMM_WORLD
rank = comm.Get_rank()

# dos defenition part
def do_dos ( data_controller, emin, emax, ne, delta ):

  arry,attr = data_controller.data_dicts()
  bnd = attr['bnd']
  netot = attr['nkpnts']*bnd
  emax = np.amin(np.array([attr['shift'], emax]))
  arry['dos'] = np.empty((ne,), dtype=float)
  # DOS calculation with gaussian smearing
  ene = np.linspace(emin, emax, ne)

  if rank == 0 and attr['verbose']:
    print('Writing DoS Files')

  for ispin in range(attr['nspin']):

    dosaux = np.zeros((ne), order="C")

    E_k = arry['E_k'][:,:bnd,ispin]

    for n in range(ne):
      dosaux[n] = np.sum(np.exp(-((ene[n]-E_k)/delta)**2)) # this should be multiplied by squared atwfcr (line 90)

    dos = np.zeros((ne), dtype=float) if rank == 0 else None

    comm.Reduce(dosaux,dos,op=MPI.SUM)
    dosaux = None

    if rank == 0:
      dos *= float(bnd)/(float(netot)*np.sqrt(np.pi)*delta)
      arry['dos'] = dos
    fdos = 'dos_%s.dat'%str(ispin)
    data_controller.write_file_row_col(fdos, ene, dos)
    data_controller.broadcast_single_array('dos', dtype=float)
    
# charge density part
def do_density ( data_controller, nr1, nr2, nr3, internal=False):

  arry,attr = data_controller.data_dicts()

  # Calculation of the electron density

  if rank == 0 and attr['verbose']:
    print('Writing density files')

  rhoaux = np.zeros((nr1,nr2,nr3,attr['nspin']),dtype=complex,order="C")

  ini_ik,end_ik = load_balancing(comm.Get_size(), rank, attr['nkpnts'])
  if not 'basis' in arry.keys():
    if internal:
      basis,attr['shells'] = build_aewfc_basis(data_controller)
    else:
      basis,attr['shells'] = build_pswfc_basis_all(data_controller)
  else:
    basis = arry['basis']
  eps = 1.e-5
  for ispin in range(attr['nspin']):
    for ik in range(ini_ik,end_ik):
      gkspace = calc_gkspace(data_controller,ik,gamma_only=False)
      atwfcgk = calc_atwfc_k(basis,gkspace,attr['dftSO'])
      oatwfcgk = ortho_atwfc_k(atwfcgk)
      atwfcr = fft_allwfc_G2R(oatwfcgk,gkspace, nr1, nr2, nr3, attr['omega'])
      for nb in range(attr['bnd']):
        if arry['E_k'][ik-ini_ik,nb,ispin] <= 0.0+eps:
          tmp = np.tensordot(arry['v_k'][ik-ini_ik,:,nb,ispin],atwfcr[:,:,:,:],axes=(0,0))
          rhoaux[:,:,:,ispin] += 2*np.conj(tmp)*tmp/attr['nkpnts']*attr['omega']/(nr1*nr2*nr3)

    rho = np.zeros((nr1,nr2,nr3,attr['nspin']),dtype=complex,order="C") if rank == 0 else None
    
    comm.Reduce(rhoaux,rho,op=MPI.SUM)
    rhoaux = None

    if rank == 0:
      fdensity = attr['outputdir']+'/density_%s.xsf'%str(ispin)
      write2xsf(data_controller,filename=fdensity,data=np.real(rho[:,:,:,ispin]))
  if rank == 0:
    if attr['verbose']: print('Total charge = ',np.real(np.sum(rho)).round(3))
