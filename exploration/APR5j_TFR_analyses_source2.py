#!/usr/bin/env python3
# -*- coding: utf-8 -*-
proj_name = 'MINDLAB2020_MEG-AuditoryPatternRecognition'
wdir = '/projects/' + proj_name + '/scratch/working_memory/'
scripts_dir = '/projects/' + proj_name + '/scripts/working_memory/'
import sys
sys.path.append(scripts_dir)

import mne
import os
import os.path as op
import numpy as np
from mne.time_frequency import tfr_morlet
import matplotlib.pyplot as plt
import pickle
from sys import argv
from stormdb.access import Query
from warnings import filterwarnings
from copy import deepcopy
from src.preprocessing import WM_epoching, main_task_events_fun, default_events_fun

#matplotlib.use('Qt4Agg')
filterwarnings("ignore", category=DeprecationWarning)

# set paths and other variables
project = 'MINDLAB2020_MEG-AuditoryPatternRecognition'
project_dir = '/projects/' + project
os.environ['MINDLABPROJ']=project
os.environ['MNE_ROOT']='/users/david/miniconda3/envs/mne3d' # for surfer
os.environ['MESA_GL_VERSION_OVERRIDE'] = '3.2'

raw_path = project_dir + '/scratch/maxfiltered_data/tsss_st16_corr96'
ica_path = project_dir + '/scratch/working_memory/ICA'
avg_path = project_dir + '/scratch/working_memory/averages'
subjects_dir = project_dir + '/scratch/fs_subjects_dir'
fwd_path = project_dir + '/scratch/forward_models'
log_path = project_dir + '/misc/working_memory_logs'

## Get subject codes
qr = Query(project)
sub_codes = qr.get_subjects()
sub_n = 24

if len(argv) > 1:
    sub_n = int(argv[1])
sub = sub_codes[sub_n-1]

band_names = ['delta','theta','alpha','beta1','beta2']
if len(argv) > 2:
    band_names = argv[2:]

## Load forward solution
fwd_fn = op.join(fwd_path, sub + '_vol-fwd.fif')
fwd = mne.read_forward_solution(fwd_fn)

## Conditions to analyse
conds_orig = ['main','inv']
conds = ['maintenance','manipulation']
lnames = ['recognize','invert']
event_ids = [[['same',1],['different',2]],[['inverted',3],['other',4]]]
chans = 'mag' # select channels to do the inversion
reject = dict(mag = 4e-12, grad = 4000e-13)

# Preprocess data looping over blocks:
epochs = {}
power = {}
for cidx, c in enumerate(conds_orig):
    nc = conds[cidx]
    # Load data, apply ICA and resample
       # event_id = dict(event_ids[cidx])
    #picks = mne.pick_types(raw.info, meg = True)
    tmin, tmax = -1.25, 6.5 #epoch time
    baseline = (-1.25, 0) # baseline time
    fname = os.path.join(raw_path, sub, c + '_raw_tsss.fif')
    icaname = os.path.join(ica_path,sub, c + '_raw_tsss-ica.fif')
    lfname = op.join(log_path, sub[0:4] + '_' + lnames[cidx] + '_MEG.csv')
    epochs[nc] = WM_epoching(data_path=fname, ica_path=icaname, tmin=tmin, tmax=tmax,
                            l_freq=None, h_freq=None, resample = 100, bads=[],
                            baseline=baseline, notch_filter=50,
                            events_fun=main_task_events_fun, events_fun_kwargs = {'cond': nc, 'lfname': lfname},
                                    reject=reject)
    epochs[nc] = epochs[nc].pick_types(chans)
#     raw = mne.io.read_raw_fif(fname, preload = True) # load data
#     ica = mne.preprocessing.read_ica(icaname) # load ica solution
#     raw = ica.apply(raw) # apply ICA
#     raw.resample(100)

#     # Get and correct triggers:
#     events = mne.find_events(raw, shortest_event = 1)
#     events = events[np.append(np.diff(events[:,0]) >2,True)] # delete spurious t
#     events2 = events.copy()
#     events2 = events2[events[:,2] < 20]
#     events2[:,2] = events[np.isin(events[:,2]//10,[11,21]),2]//100 + cidx*2# recode events

#     # Epoching parameters:
#     event_id = dict(event_ids[cidx])
#     picks = mne.pick_types(raw.info, meg = True)
#     tmin, tmax = -1.25, 6.5 #epoch time
#     baseline = (-1.25, 0) # baseline time
#     reject = dict(mag = 8e-12, grad = 4000e-13) #eeg = 200e-6, #, eog = 250e-6)

#     #epoching:
#     epochs[c] = mne.Epochs(raw, events = events2, event_id = event_id,
#                     tmin = tmin, tmax = tmax, picks = picks,
#                     baseline = baseline, reject = reject)
### TFR analyses
# put all epochs together and select channels
all_epochs = mne.epochs.concatenate_epochs([epochs[c] for c in epochs])
all_epochs.pick_types(chans)
sfreq = all_epochs.info['sfreq']
del epochs # free memory
#del raw
## Transform to source space:
## calculate data covariance
data_cov = mne.compute_covariance(all_epochs, tmin= -1, tmax = 6.5, rank =None)

## compute inverse solution
inv = mne.beamformer.make_lcmv(all_epochs.info, fwd, data_cov, reg=0.05,
                                  weight_norm= 'nai', rank = None, pick_ori='max-power')

bands = {'delta': [1.,3.], 'theta': [4.,8.], 'alpha': [9.,13.], 'beta1': [14.,20.], 'beta2': [21.,30.]}

sconds = ['maintenance','manipulation','mel1','mel2',
          'maintenance/mel1','maintenance/mel2','manipulation/mel1',
         'manipulation/mel2','same','diff1','diff2','inv','other1','other2']
for bidx, bname in enumerate(band_names):
    b = bands[bname]
    print('processing band {}'.format(bname))
    freqs = np.arange(b[0], b[1]+1, 1)
    n_cycles = freqs / 2.
    n_cycles[np.where(n_cycles < 2)] = 2
    stc_pwr = {}
    sbpwr = {} #np.zeros(1,inv['n_sources'], len(freqs), len(all_epochs.times))
    for fidx in range(len(freqs)):
        freq = [freqs[fidx]]
        cpwr = np.zeros((len(all_epochs.events), inv['n_sources'], 1, len(all_epochs.times)))
        for eix, epoch in enumerate(all_epochs.iter_evoked()):
            #if eix < 2:
            print('decomposing epoch {}'.format(eix+1))
            stc = mne.beamformer.apply_lcmv(epoch, inv, max_ori_out = 'signed')
            cdata = np.expand_dims(stc.data, axis = 0)
            cpwr[eix, :, :, :] = np.log(mne.time_frequency.tfr_array_morlet(cdata,
                                                                    sfreq, freq,
                                                                    n_cycles=n_cycles[fidx],
                                                                    output='avg_power',
                                                                    n_jobs=-1))
        del cdata
        btidx = np.where([x and y for x, y in zip(stc.times >= -1, stc.times <= 0)])
        bmean = np.mean(np.squeeze(cpwr[:,:,:,btidx], axis = 3),  axis = (0,3), keepdims = True)
        bstd =  np.std(np.squeeze(cpwr[:,:,:,btidx], axis = 3), axis = (0,3), keepdims = True)

#         print(bmean.shape)
#         print(bstd.shape)
        for trix in range(cpwr.shape[0]):
            print('z scoring epoch {}'.format(trix+1))
            cpwr[trix,:,:,:] -= bmean[0,...]
            cpwr[trix,:,:,:] /= bstd[0,...]
            bmean2 = np.squeeze(np.mean(cpwr[trix][:,:,btidx], axis = -1,keepdims=True))
            print(bmean2.shape)
            cpwr[trix,:,:,:] -= bmean2[:,None,None]
        del bmean2          
        del bmean
        del bstd
        print(cpwr.shape)
        for eid in sconds:#all_epochs.event_id.keys():
            print('averaging source power for band {} condition {} frequency {}'.format(bname,eid,freq))
            eidx = np.array([e in all_epochs[eid].events[:,2] for e in all_epochs.events[:,2]])
            sbpwr.setdefault(eid, np.zeros((inv['n_sources'], len(freqs), len(all_epochs.times))))
            mnpwr = np.mean(cpwr[eidx,:,:,:],axis=0)
            sbpwr[eid][:,fidx,:] = np.squeeze(mnpwr)
        del cpwr
        del mnpwr
                             
    for eid in sbpwr:
        stc_pwr[eid] = deepcopy(stc)
        stc_pwr[eid].data = sbpwr[eid].mean(axis=1)    
    del sbpwr
    
    src_fname = op.join(avg_path,'data', sub + '_TFR_src2_' + bname + '.p')
    src_file = open(src_fname,'wb')
    pickle.dump(stc_pwr, src_file)
    src_file.close()
    print('src file saved')
    del stc
    del stc_pwr

#src_fname = op.join(avg_path,'data', sub + '_TFR_src2.p')

# src_file = open(src_fname,'wb')
# pickle.dump(stc_pwr, src_file)
# src_file.close()
# print('src file saved')

# all_freqs = np.arange(4,31)
# print(all_freqs)
# n_cycles = all_freqs / 2
# cpower_data = tfr_morlet(all_epochs, freqs = all_freqs, n_cycles= n_cycles,
#                          use_fft = True, return_itc = False, decim = 1,
#                          average = False, n_jobs=-1)
# cpower_data.data = np.log(cpower_data.data)
#
# # Define frequency bands
# bands = [[4,8],[9,13],[14,20],[21,30]]
# band_names = ['theta','alpha','beta1','beta2']
#
# # Average power per band
# mean_pwr = {}
# for bidx, b in enumerate(bands):
#     fidx = np.where([x and y for x, y in zip((all_freqs >= b[0]), (all_freqs <= b[1]))])
#     cpdata = np.squeeze(cpower_data.data[:,:,fidx,:])
#     mean_pwr[band_names[bidx]] = cpdata.mean(axis = 2, keepdims=False)
#
# del cpower_data
# del cpdata
#
# # Loop over bands, calculate power time courses and source estimates
# inv, src  = {}, {}
# for b in mean_pwr: #enumerate(bands):
#     cpower = mne.EpochsArray(mean_pwr[b], all_epochs.info, events=all_epochs.events,
#                              event_id = all_epochs.event_id, tmin = baseline[0])
#     ## Source analyses
#     ## calculate data covariance
#     data_cov = mne.compute_covariance(cpower, tmin= -1, tmax = 6.5, rank =None)
#
#     ## compute inverse solution
#     inv[b] = mne.beamformer.make_lcmv(cpower.info, fwd, data_cov, reg=0.05,
#                                       weight_norm= 'nai', rank = None)
#
#     #### Z-score power with baseline
#     # calculate power at baseline (-1 to 0)
#     bpwr = mne.beamformer.apply_lcmv_epochs(cpower.copy().crop(-1,0), inv[b])
#     bdata = np.array([p.data for p in bpwr])
#     del bpwr # free memory
#
#     # Calculate mean and sd for the baseline across trials
#     bdata = np.transpose(bdata,[0,2,1])
#     bdata = bdata.reshape((bdata.shape[0]*bdata.shape[1], bdata.shape[2]))
#     bmean = np.mean(bdata.copy(), 0,  keepdims = True).transpose([1,0])
#     bsd =  np.std(bdata.copy(), 0,  keepdims = True).transpose([1,0])
#     del bdata #free memory
#
#     # calculate source power, z-score with baseline and average trials
#     src[b] = {}
#     for cond in cpower.event_id.keys():
#         csrc = mne.beamformer.apply_lcmv_epochs(cpower[cond], inv[b])
#         src[b][cond] = deepcopy(csrc[0])
#         cdata = np.array([(p.data - bmean) / bsd for p in csrc])
#         del csrc # free memory
#         src[b][cond].data = np.mean(cdata, 0)
#         del cdata # free memory
#     del cpower # free memory
#
# ### Save solution
# inv_fname = op.join(avg_path,'data', sub + '_TFR_inv.p')
# src_fname = op.join(avg_path,'data', sub + '_TFR_src.p')
#
# inv_file = open(inv_fname,'wb')
# pickle.dump(inv,inv_file)
# inv_file.close()
# print('inv file saved')
#
# src_file = open(src_fname,'wb')
# pickle.dump(src, src_file)
# src_file.close()
# print('src file saved')
