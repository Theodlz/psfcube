#! /usr/bin/env python
# -*- coding: utf-8 -*-

"""  """


import numpy as np



def extract_star(cube, lbda_step1=None, psfmodel="NormalMoffatTilted",
                centroids=None, only_step1=False, spaxel_unit=1, step1_fit_prop={},
                final_slice_width=None,
                force_ellipse=True, force_centroid=True, force_stddev=True, force_alpha=True):
    """ 
    Returns
    -------
    spectrum, model (cube), psfmodel (cube), bkgdmodel (cube)
    """
    
    from pyifu   import get_spectrum, get_cube
    
    if lbda_step1 is None:
        lbdaranges, bins = [5000,8000], 6
        STEP_LBDA_RANGE = np.linspace(lbdaranges[0],lbdaranges[1], bins+1)
        lbda_step1      = np.asarray([STEP_LBDA_RANGE[:-1], STEP_LBDA_RANGE[1:]]).T

        
    # Step 1
    psffit = fit_metaslices(cube, lbda_step1, 
                            psfmodel=psfmodel, 
                            centroids=centroids, spaxel_unit=spaxel_unit, **step1_fit_prop)
    if only_step1:
        return psffit
    
    # Step 2
    # ellipse_parameters
    ell, ellerr, theta, thetaerr = psffit.get_ellipse_parameters()
    
    cmodel = psffit.get_chromatic_profile_model()
    
    slfits = cmodel.force_fit(cube, ell=ell, theta=theta,
                                  ellerr=ellerr*2, thetaerr=thetaerr*2,
                                  psfmodel=psfmodel,
                                  force_ellipse=force_ellipse,
                                  force_centroid=force_centroid,
                                  force_stddev=force_stddev, force_alpha=force_alpha,
                                  slice_width=final_slice_width,
                                  )
    lbdas = np.asarray([slfits[i].lbda for i in range(len(slfits))])
    # Returns all structures
    cube_prop = dict(header=cube.header, lbda=lbdas,
                    spaxel_mapping = cube.spaxel_mapping, spaxel_vertices=cube.spaxel_vertices)

    # Background
    databkgd = np.asarray([slfits[i].model.get_background(slfits[i]._xfitted, slfits[i]._yfitted)
                                           for i in range(len(lbdas))])
    if len(np.shape(databkgd)) ==1: # means "Flat"
        databkgd = np.asarray([databkgd for i in range(len(cube.indexes))]).T
        
    bkgdmodel = get_cube(  databkgd, **cube_prop)
    # PSF
    psfmodel  = get_cube(  np.asarray([slfits[i].model.get_profile(slfits[i]._xfitted, slfits[i]._yfitted)
                                           for i in range(len(lbdas))]),
                        **cube_prop)
    # Complit Model
    model     = get_cube(  np.asarray([slfits[i].model.get_model(slfits[i]._xfitted, slfits[i]._yfitted)
                                           for i in range(len(lbdas))]),
                        **cube_prop)
    # = The spectrum
    flux,err  = np.asarray([[slfits[i].fitvalues["amplitude"],slfits[i].fitvalues["amplitude.err"]]  for i in range(len(lbdas))]).T
    spectrum  = get_spectrum(lbdas, flux, variance=err**2, header=cube.header)
    
    return spectrum, model, psfmodel, bkgdmodel, psffit, slfits


    
def build_parameter_prior(filenames, centroids=None, psfmodel="NormalMoffatTilted", lbdaranges=[4000,8500], bins=10):
    """ """
    prop_fit = {}

    STEP_LBDA_RANGE = np.linspace(lbdaranges[0],lbdaranges[1], bins+1)
    lbdas           = np.asarray([STEP_LBDA_RANGE[:-1], STEP_LBDA_RANGE[1:]]).T
    
    def _fit_cube_(cube):
        psffit = SlicePSFCollection()
        psffit.set_cube(cube)
        for i,lbdar in enumerate(lbdas):
            psffit.extract_slice(i, *lbdar)
            slpsf = psffit.fit_slice(i, psfmodel=psfmodel,
                                        **prop_fit)
            return slpsf
        
    return {filename_: _fit_cube_(pysedm.get_sedmcube(filename_)) for filename_ in filenames}


def fit_metaslices(cube, lbdas, psfmodel="NormalMoffatTilted",
                       centroids=None, centroids_err=[5,5],
                       spaxel_unit=1,
                       **kwargs):
    """ """
    from .fitter import SlicePSFCollection
    psffit = SlicePSFCollection()
    psffit.set_cube(cube)

    for i,lbdar in enumerate(lbdas):
        psffit.extract_slice(i, *lbdar)
        slpsf = psffit.fit_slice(i, psfmodel=psfmodel,
                                       centroids=centroids,
                            centroids_err=centroids_err, **kwargs)

    psffit.load_adrfitter(spaxel_unit=spaxel_unit)
    psffit.fit_adr()
    return psffit

def automatic_fit_psf(cube, centroids=[0,0],
                        centroids_err=[3,3],
                        psfmodel="NormalMoffatTilted", step_bins=[3,10]):
    """ """
    prop_fit = dict(ell_boundaries=[0.01,0.5])
    # ================== #
    # Step 1: 5 slices  #
    #  All Free          #
    # ================== #
    STEP1_LBDA_RANGE = np.linspace(4500,8000, step_bins[0]+1)
    step1_lbdas = np.asarray([STEP1_LBDA_RANGE[:-1], STEP1_LBDA_RANGE[1:]]).T

    psffit_step1 = SlicePSFCollection()
    psffit_step1.set_cube(cube)

    for i,lbdar in enumerate(step1_lbdas):
        psffit_step1.extract_slice(i, *lbdar)
        slpsf = psffit_step1.fit_slice(i, psfmodel=psfmodel,
                                       centroids=centroids,
                            centroids_err=centroids_err, **prop_fit)

    psffit_step1.load_adrfitter()
    psffit_step1.fit_adr()
    if len(step_bins)==1 or step_bins[1] is None:
        return psffit_step1, None
    
    # ================== #
    # Step 2: 15 slices  #
    #  Strong centroid   #
    # ================== #
    # - Helping on the ellipticity
    [mean_ell, mean_ellerr, mean_theta, mean_thetaerr], mask_removed  = psffit_step1.get_ellipse_parameters()
    stddev_ratio,stddev_ratioerr = psffit_step1.get_stddev_ratio()
    
    STEP2_LBDA_RANGE = np.linspace(4500,8000, step_bins[1]+1)
    step2_lbdas = np.asarray([STEP2_LBDA_RANGE[:-1], STEP2_LBDA_RANGE[1:]]).T
    STEP2_CENTROID_ERROR = [0.2, 0.2]
    
    psffit_step2 = SlicePSFCollection()
    psffit_step2.set_cube(cube)

    prop_fit["ell_guess"] = mean_ell
    prop_fit["ell_boundaries"] = [mean_ell-mean_ellerr, mean_ell+mean_ellerr]

    prop_fit["theta_guess"] = mean_theta
    prop_fit["theta_boundaries"] = [mean_theta-mean_thetaerr, mean_theta+mean_thetaerr]

    prop_fit["stddev_ratio_guess"] = stddev_ratio
    prop_fit["stddev_ratio_boundaries"] = [stddev_ratio-stddev_ratioerr, stddev_ratio+stddev_ratioerr]
    
    
    for i,lbdar in enumerate(step2_lbdas):
        centroids = psffit_step1.get_adr_centroid( np.mean(lbdar) )
        psffit_step2.extract_slice(i, *lbdar)
        slpsf = psffit_step2.fit_slice(i, psfmodel=psfmodel,
                                        centroids=centroids,
                                        centroids_err=STEP2_CENTROID_ERROR, **prop_fit)

    psffit_step2.load_adrfitter()
    psffit_step2.fit_adr()

    # ================== #
    # Step 2: 15 slices  #
    #  Strong centroid   #
    # ================== #


    return psffit_step1, psffit_step2
