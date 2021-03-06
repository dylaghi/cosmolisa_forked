#!/usr/bin/env python
# -*- coding: utf-8 -*-
from __future__ import unicode_literals
import unittest
import numpy as np
import lal
import cpnest.model
import sys
import os
from optparse import OptionParser
import itertools as it
import cosmology as cs
import readdata
from scipy.special import logsumexp
import likelihood as lk
from functools import reduce

"""
G = the GW is in a galaxy that i see
N = the GW is in a galaxy that i do not see
D = a GW
I = i see only GW with SNR > 20

p(H|D(G+N)I) \propto p(H|I)p(D(G+N)|HI)
p(D(G+N)|HI) = p(DG+DN|HI) = p(DG|HI)+p(DN|HI) = p(D|GHI)p(G|HI)+p(D|NHI)p(N|HI) = p(D|HI)(p(G|HI)+p(N|HI))
"""

class CosmologicalModel(cpnest.model.Model):

    names=[]#'h','om','ol','w0','w1']
    bounds=[]#[0.5,1.0],[0.04,1.0],[0.0,1.0],[-2.0,0.0],[-3.0,3.0]]
    
    def __init__(self, model, data, *args, **kwargs):

        super(CosmologicalModel,self).__init__()
        # Set up the data
        self.data           = data
        self.N              = len(self.data)
        self.model          = model
        self.em_selection   = kwargs['em_selection']
        self.z_threshold    = kwargs['z_threshold']
        self.snr_threshold  = kwargs['snr_threshold']
        self.event_class    = kwargs['event_class']
        self.O              = None
        
        if self.model == "LambdaCDM":
            
            self.names  = ['h','om']
            self.bounds = [[0.5,1.0],[0.04,0.5]]
        
        elif self.model == "LambdaCDMDE":
            
            self.names  = ['h','om','ol','w0','w1']
            self.bounds = [[0.5,1.0],[0.04,0.5],[0.0,1.0],[-2.0,0.0],[-3.0,3.0]]
            
        elif self.model == "CLambdaCDM":
            
            self.names  = ['h','om','ol']
            self.bounds = [[0.5,1.0],[0.04,0.5],[0.0,1.0]]
            
        elif self.model == "DE":
            
            self.names  = ['w0','w1']
            self.bounds = [[-3.0,0.3],[-1.0,1.0]]
        
        else:
            
            print("Cosmological model %s not supported. exiting..\n"%self.model)
            exit()
        
        for e in self.data:
            self.bounds.append([e.zmin,e.zmax])
            self.names.append('z%d'%e.ID)
            
        self._initialise_galaxy_hosts()
        
        print("==========================================")
        print("cpnest model initialised with:")
        print("Cosmological model: {0}".format(self.model))
        print("Number of events: {0}".format(len(self.data)))
        print("EM correction: {0}".format(self.em_selection))
        print("==========================================")

    def _initialise_galaxy_hosts(self):
        self.hosts = {e.ID:np.array([(g.redshift,g.dredshift,g.weight) for g in e.potential_galaxy_hosts]) for e in self.data}
        
    def log_prior(self,x):
        logP = super(CosmologicalModel,self).log_prior(x)
        
        if np.isfinite(logP):
            """
            apply a uniform in comoving volume density redshift prior
            """
            if self.model == "LambdaCDM":
                z_idx = 2
                self.O = cs.CosmologicalParameters(x['h'],x['om'],1.0-x['om'],-1.0,0.0)
            elif self.model == "LambdaCDMDE":
                z_idx = 5
                self.O = cs.CosmologicalParameters(x['h'],x['om'],x['ol'],x['w0'],x['w1'])
                
            elif self.model == "CLambdaCDM":
                z_idx = 3
                self.O = cs.CosmologicalParameters(x['h'],x['om'],x['ol'],-1.0,0.0)
            
            elif self.model == "DE":
                z_idx = 2
                self.O = cs.CosmologicalParameters(0.73,0.25,0.75,x['w0'],x['w1'])
            
#            if self.event_class == "EMRI" or self.event_class == "sBH":
#                for j,e in enumerate(self.data):
#                    #log_norm = np.log(self.O.IntegrateComovingVolumeDensity(self.bounds[z_idx+j][1]))
#                    logP += np.log(self.O.UniformComovingVolumeDensity(x['z%d'%e.ID]))#-log_norm
                
        return logP

    def log_likelihood(self,x):
        
        # compute the p(GW|G\Omega)p(G|\Omega)+p(GW|~G\Omega)p(~G|\Omega)
        logL = np.sum([lk.logLikelihood_single_event(self.hosts[e.ID], e.dl, e.sigma, self.O, x['z%d'%e.ID],
                                em_selection = self.em_selection, zmin = self.bounds[2+j][0], zmax = self.bounds[2+j][1]) for j,e in enumerate(self.data)])

        self.O.DestroyCosmologicalParameters()

        return logL

truths = {'h':0.73,'om':0.25,'ol':0.75,'w0':-1.0,'w1':0.0}
usage=""" %prog (options)"""

if __name__=='__main__':

    parser=OptionParser(usage)
    parser.add_option('-o','--out-dir', default=None,type='string',metavar='DIR',help='Directory for output')
    parser.add_option('-t','--threads', default=None,type='int',metavar='threads',help='Number of threads (default = 1/core)')
    parser.add_option('-d','--data',    default=None,type='string',metavar='data',help='galaxy data location')
    parser.add_option('-e','--event',   default=None,type='int',metavar='event',help='event number')
    parser.add_option('-c','--event-class',default=None,type='string',metavar='event_class',help='class of the event(s) [MBH, EMRI, sBH]')
    parser.add_option('-m','--model',   default='LambdaCDM',type='string',metavar='model',help='cosmological model to assume for the analysis (default LambdaCDM). Supports LambdaCDM, CLambdaCDM, DE and LambdaCDMDE')
    parser.add_option('-j','--joint',   default=0, type='int',metavar='joint',help='run a joint analysis for N events, randomly selected. (EMRI only)')
    parser.add_option('-s','--seed',   default=0, type='int', metavar='seed',help='rando seed initialisation')
    parser.add_option('--snr_threshold',    default=0, type='float',metavar='snr_threshold',help='SNR detection threshold')
    parser.add_option('--zhorizon',     default=1000.0, type='float',metavar='zhorizon',help='Horizon redshift corresponding to the SNR threshold')
    parser.add_option('--em_selection', default=0, type='int',metavar='em_selection',help='use EM selection function')
    parser.add_option('--nlive',        default=1000, type='int',metavar='nlive',help='number of live points')
    parser.add_option('--poolsize',     default=100, type='int',metavar='poolsize',help='poolsize for the samplers')
    parser.add_option('--maxmcmc',      default=1000, type='int',metavar='maxmcmc',help='maximum number of mcmc steps')
    parser.add_option('--postprocess',  default=0, type='int',metavar='postprocess',help='run only the postprocessing')
    (opts,args)=parser.parse_args()
    
    em_selection = opts.em_selection

    if opts.event_class == "MBH":
        # if running on SMBH override the selection functions
        em_selection = 0

    if opts.event_class == "EMRI" and opts.joint !=0:
        np.random.seed(opts.seed)
        events = readdata.read_event(opts.event_class, opts.data, None)
        N = opts.joint#np.int(np.random.poisson(len(events)*4./10.))
        print("Will run a random catalog selection of {0} events:".format(N))
        print("==================================================")
        selected_events  = []
        count = 0
        if 1:
            while len(selected_events) < N-count and not(len(events) == 0):

                while True:
                    if len(events) > 0:
                        idx = np.random.randint(len(events))
                        selected_event = events.pop(idx)
                    else:
                        break
                    if selected_event.z_true < opts.zhorizon:
                        selected_events.append(selected_event)
                        count += 1
                        break
            
            events = np.copy(selected_events)
        else: events = np.random.choice(events, size = N, replace = False)
        for e in events:
            print("event {0}: distance {1} \pm {2} Mpc, z \in [{3},{4}] galaxies {5}".format(e.ID,e.dl,e.sigma,e.zmin,e.zmax,len(e.potential_galaxy_hosts)))
        print("==================================================")
    else:
        events = readdata.read_event(opts.event_class, opts.data, opts.event)

#    redshifts = [e.z_true for e in events]
#    galaxy_redshifts = [g.redshift for e in events for g in e.potential_galaxy_hosts]
#
#    import matplotlib
#    import matplotlib.pyplot as plt
#    fig = plt.figure(figsize=(10,8))
#    z = np.linspace(0.0,0.63,100)
#    normalisation = matplotlib.colors.Normalize(vmin=0.5, vmax=1.0)
#    normalisation2 = matplotlib.colors.Normalize(vmin=0.04, vmax=1.0)
#    # choose a colormap
#    c_m = matplotlib.cm.cool
#
#    # create a ScalarMappable and initialize a data structure
#    s_m = matplotlib.cm.ScalarMappable(cmap=c_m, norm=normalisation)
#    s_m.set_array([])
#
#    # choose a colormap
#    c_m2 = matplotlib.cm.rainbow
#
#    # create a ScalarMappable and initialize a data structure
#    s_m2 = matplotlib.cm.ScalarMappable(cmap=c_m2, norm=normalisation2)
#    s_m2.set_array([])
#
#    plt.hist(redshifts, bins=z, density=True, alpha = 0.5, facecolor="yellow", cumulative=True)
#    plt.hist(redshifts, bins=z, density=True, alpha = 0.5, histtype='step', edgecolor="k", cumulative=True)
##    plt.hist(galaxy_redshifts, bins=z, density=True, alpha = 0.5, facecolor="green", cumulative=True)
##    plt.hist(galaxy_redshifts, bins=z, density=True, alpha = 0.5, histtype='step', edgecolor="k", linestyle='dashed', cumulative=True)
#    for _ in range(1000):
#        h = np.random.uniform(0.5,1.0)
#        om = np.random.uniform(0.04,1.0)
#        ol = 1.0-om
##        h = 0.73
##        om = 0.25
##        ol = 1.0-om
#        O = cs.CosmologicalParameters(h,om,ol,-1.0,0.0)
##        distances = np.array([O.LuminosityDistance(zi) for zi in z])
##        plt.plot(z, [lk.em_selection_function(d) for d in distances], lw = 0.25, color=s_m.to_rgba(h), alpha = 0.75, linestyle='dashed')
#        pz = np.array([O.UniformComovingVolumeDensity(zi) for zi in z])/O.IntegrateComovingVolumeDensity(z.max())
##        pz = np.array([O.ComovingVolumeElement(zi) for zi in z])/O.IntegrateComovingVolume(z.max())
#        plt.plot(z,np.cumsum(pz)/pz.sum(), lw = 0.15, color=s_m2.to_rgba(om), alpha = 0.5)
#        O.DestroyCosmologicalParameters()
#
##        p = lal.CreateCosmologicalParametersAndRate()
##        p.omega.h = h
##        p.omega.om = om
##        p.omega.ol = ol
##        p.omega.w0 = -1.0
##
##        p.rate.r0 = 1e-12
##        p.rate.W  = np.random.uniform(0.0,10.0)
##        p.rate.Q  = np.random.normal(0.63,0.01)
##        p.rate.R  = np.random.normal(1.0,0.1)
##        pz = np.array([lal.RateWeightedUniformComovingVolumeDensity(zi, p) for zi in z])/lal.IntegrateRateWeightedComovingVolumeDensity(p,z.max())
##        plt.plot(z, np.cumsum(pz)/pz.sum(), color=s_m2.to_rgba(om), linewidth = 0.5, linestyle='solid', alpha = 0.5)
##        lal.DestroyCosmologicalParametersAndRate(p)
##        plt.plot(z, pz/(pz*np.diff(z)[0]).sum(), color=s_m2.to_rgba(om), linewidth = 0.5, linestyle='solid', alpha = 0.5)
#
#
#
#    O = cs.CosmologicalParameters(0.73,0.25,0.75,-1.0,0.0)
#    pz = np.array([O.ComovingVolumeElement(zi) for zi in z])/O.IntegrateComovingVolume(z.max())
#    pz = np.array([O.UniformComovingVolumeDensity(zi) for zi in z])/O.IntegrateComovingVolumeDensity(z.max())
#    distances = np.array([O.LuminosityDistance(zi) for zi in z])
#    plt.plot(z, [lk.em_selection_function(d) for d in distances], lw = 0.5, color='k', linestyle='dashed')
#    O.DestroyCosmologicalParameters()
#    plt.plot(z,np.cumsum(pz)/pz.sum(), lw = 0.5, color='k')
##    plt.plot(z,pz/(pz*np.diff(z)[0]).sum(), lw = 0.5, color='k')
#    CB = plt.colorbar(s_m, orientation='vertical', pad=0.15)
#    CB.set_label(r'$h$')
#    CB = plt.colorbar(s_m2, orientation='horizontal', pad=0.15)
#    CB.set_label(r'$\Omega_m$')
#    plt.xlabel('redshift')
##    plt.xlim(0.,0.3)
#    plt.show()
#    exit()

    model = opts.model

    if opts.out_dir is None:
        output = opts.data+"/EVENT_1%03d/"%(opts.event+1)
    else:
        output = opts.out_dir
    
    C = CosmologicalModel(model,
                          events,
                          em_selection = em_selection,
                          snr_threshold= opts.snr_threshold,
                          z_threshold  = opts.zhorizon,
                          event_class  = opts.event_class)
    
    if opts.postprocess == 0:
        work=cpnest.CPNest(C,
                           verbose      = 2,
                           poolsize     = opts.poolsize,
                           nthreads     = opts.threads,
                           nlive        = opts.nlive,
                           maxmcmc      = opts.maxmcmc,
                           output       = output,
                           nhamiltonian = 0)

        work.run()
        print('log Evidence {0}'.format(work.NS.logZ))
        x = work.posterior_samples.ravel()
    else:
        x = np.genfromtxt(os.path.join(output,"chain_"+str(opts.nlive)+"_1234.txt"), names=True)
        from cpnest import nest2pos
        x = nest2pos.draw_posterior_many([x], [opts.nlive], verbose=False)

    import matplotlib
    import matplotlib.pyplot as plt
    from scipy.stats import norm
    
    if opts.event_class == "EMRI":
        for e in C.data:
            fig = plt.figure()
            ax  = fig.add_subplot(111)
            z = np.linspace(e.zmin,e.zmax, 100)
            
            ax2 = ax.twinx()
            
            if model == "DE": normalisation = matplotlib.colors.Normalize(vmin=np.min(x['w0']), vmax=np.max(x['w0']))
            else: normalisation = matplotlib.colors.Normalize(vmin=np.min(x['h']), vmax=np.max(x['h']))
            # choose a colormap
            c_m = matplotlib.cm.cool

            # create a ScalarMappable and initialize a data structure
            s_m = matplotlib.cm.ScalarMappable(cmap=c_m, norm=normalisation)
            s_m.set_array([])
            ax.axvline(e.z_true, linestyle='dotted', lw=0.5, color='k')
            for i in range(x.shape[0])[::10]:
                if model == "LambdaCDM": O = cs.CosmologicalParameters(x['h'][i],x['om'][i],1.0-x['om'][i],-1.0,0.0)
                elif model == "LambdaCDMDE": O = cs.CosmologicalParameters(x['h'][i],x['om'][i],x['ol'][i],x['w0'][i],x['w1'][i])
                elif model == "CLambdaCDM": O = cs.CosmologicalParameters(x['h'][i],x['om'][i],x['ol'][i],-1.0,0.0)
                elif model == "DE": O = cs.CosmologicalParameters(truths['h'],truths['om'],truths['ol'],x['w0'][i],x['w1'][i])
                distances = np.array([O.LuminosityDistance(zi) for zi in z])
                if model == "DE":  ax2.plot(z, [lk.em_selection_function(d) for d in distances], lw = 0.15, color=s_m.to_rgba(x['w0'][i]), alpha = 0.5)
                else: ax2.plot(z, [lk.em_selection_function(d) for d in distances], lw = 0.15, color=s_m.to_rgba(x['h'][i]), alpha = 0.5)
                O.DestroyCosmologicalParameters()
                
            CB = plt.colorbar(s_m, orientation='vertical', pad=0.15)
            if model == "DE": CB.set_label('w_0')
            else: CB.set_label('h')
            ax2.set_ylim(0.0,1.0)
            ax2.set_ylabel('selection function')
            ax.hist(x['z%d'%e.ID], bins=z, density=True, alpha = 0.5, facecolor="green")
            ax.hist(x['z%d'%e.ID], bins=z, density=True, alpha = 0.5, histtype='step', edgecolor="k")

            for g in e.potential_galaxy_hosts:
                zg = np.linspace(g.redshift - 5*g.dredshift, g.redshift+5*g.dredshift, 100)
                pg = norm.pdf(zg, g.redshift, g.dredshift*(1+g.redshift))*g.weight
                ax.plot(zg, pg, lw=0.5,color='k')
            ax.set_xlabel('$z_{%d}$'%e.ID)
            ax.set_ylabel('probability density')
            plt.savefig(os.path.join(output,'redshift_%d'%e.ID+'.pdf'), bbox_inches='tight')
            plt.close()
    
    if opts.event_class == "MBH":
        dl = [e.dl/1e3 for e in C.data]
        ztrue = [e.potential_galaxy_hosts[0].redshift for e in C.data]
        dztrue = np.squeeze([[ztrue[i]-e.zmin,e.zmax-ztrue[i]] for i,e in enumerate(C.data)]).T
        deltadl = [np.sqrt((e.sigma/1e3)**2+(lk.sigma_weak_lensing(e.potential_galaxy_hosts[0].redshift,e.dl)/1e3)**2) for e in C.data]
        z = [np.median(x['z%d'%e.ID]) for e in C.data]
        deltaz = [2*np.std(x['z%d'%e.ID]) for e in C.data]
        
        # injected cosmology
        omega_true = cs.CosmologicalParameters(0.73,0.25,0.75,-1,0)
        redshift = np.logspace(-3,1.0,100)
        
        # loop over the posterior samples to get all models to then average
        # for the plot
        
        models = []
        
        for k in range(x.shape[0]):
            if opts.model == "LambdaCDM":
                omega = cs.CosmologicalParameters(x['h'][k],
                                               x['om'][k],
                                               1.0-x['om'][k],
                                               -1,
                                               0.0)
            elif opts.model == "CLambdaCDM":
                omega = cs.CosmologicalParameters(x['h'][k],
                                               x['om'][k],
                                               x['ol'][k],
                                               -1,
                                               0.0)
            elif opts.model == "LambdaCDMDE":
                omega = cs.CosmologicalParameters(x['h'][k],
                                               x['om'][k],
                                               x['ol'][k],
                                               x['w0'][k],
                                               x['w1'][k])
            elif opts.model == "DE":
                omega = cs.CosmologicalParameters(0.73,
                                               0.25,
                                               0.75,
                                               x['w0'][k],
                                               x['w1'][k])
            else:
                print(opts.model,"is unknown")
                exit()
            models.append([omega.LuminosityDistance(zi)/1e3 for zi in redshift])
            omega.DestroyCosmologicalParameters()
        
        models = np.array(models)
        model2p5,model16,model50,model84,model97p5 = np.percentile(models,[2.7,16.0,50.0,84.0,97.5],axis = 0)
        
        
        fig = plt.figure()
        ax = fig.add_subplot(111)
        ax.errorbar(z,dl,xerr=deltaz,yerr=deltadl,markersize=1,linewidth=2,color='k',fmt='o')
        ax.plot(redshift,[omega_true.LuminosityDistance(zi)/1e3 for zi in redshift],linestyle='dashed',color='red', zorder = 22)
        ax.plot(redshift,model50,color='k')
        ax.errorbar(ztrue, dl, yerr=deltadl, xerr=dztrue, markersize=2,linewidth=1,color='r',fmt='o')
        ax.fill_between(redshift,model2p5,model97p5,facecolor='turquoise')
        ax.fill_between(redshift,model16,model84,facecolor='cyan')
        ax.set_xlabel(r"z")
        ax.set_ylabel(r"$D_L$/Gpc")
#        ax.set_xlim(np.min(redshift),0.8)
#        ax.set_ylim(0.0,4.0)
        fig.savefig(os.path.join(output,'regression.pdf'),bbox_inches='tight')
        plt.close()
    
    
    import corner
    if model == "LambdaCDM":
        samps = np.column_stack((x['h'],x['om']))
        fig = corner.corner(samps,
               labels= [r'$h$',
                        r'$\Omega_m$'],
               quantiles=[0.05, 0.5, 0.95],
               show_titles=True, title_kwargs={"fontsize": 12},
               use_math_text=True, truths=[0.73,0.25],
               filename=os.path.join(output,'joint_posterior.pdf'))
    
    if model == "CLambdaCDM":
        samps = np.column_stack((x['h'],x['om'],x['ol'],1.0-x['om']-x['ol']))
        fig = corner.corner(samps,
               labels= [r'$h$',
                        r'$\Omega_m$',
                        r'$\Omega_\Lambda$',
                        r'$\Omega_k$'],
               quantiles=[0.05, 0.5, 0.95],
               show_titles=True, title_kwargs={"fontsize": 12},
               use_math_text=True, truths=[0.73,0.25,0.75,0.0],
               filename=os.path.join(output,'joint_posterior.pdf'))
               
    if model == "LambdaCDMDE":
        samps = np.column_stack((x['h'],x['om'],x['ol'],x['w0'],x['w1']))
        fig = corner.corner(samps,
                        labels= [r'$h$',
                                 r'$\Omega_m$',
                                 r'$\Omega_\Lambda$',
                                 r'$w_0$',
                                 r'$w_1$'],
                        quantiles=[0.05, 0.5, 0.95],
                        show_titles=True, title_kwargs={"fontsize": 12},
                        use_math_text=True, truths=[0.73,0.25,0.75,-1.0,0.0],
                        filename=os.path.join(output,'joint_posterior.pdf'))
    if model == "DE":
        samps = np.column_stack((x['w0'],x['w1']))
        fig = corner.corner(samps,
                        labels= [r'$w_0$',
                                 r'$w_1$'],
                        quantiles=[0.05, 0.5, 0.95],
                        show_titles=True, title_kwargs={"fontsize": 12},
                        use_math_text=True, truths=[-1.0,0.0],
                        filename=os.path.join(output,'joint_posterior.pdf'))
    fig.savefig(os.path.join(output,'joint_posterior.pdf'), bbox_inches='tight')
