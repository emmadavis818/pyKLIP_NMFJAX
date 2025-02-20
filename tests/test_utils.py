import os
import pytest
import math
import numpy as np
import scipy
import astropy.io.fits as fits
import astropy.modeling as modeling
import pyklip.fakes as fakes
import pyklip.klip as klip
import pyklip.instruments.utils.nair as nair
import pyklip.instruments.utils.wcsgen as wcsgen
import pyklip.instruments.Instrument as Instrument
import pyklip.parallelized as parallelized

"""
This suite of tests is designed to test utility functions in pyKLIP
"""

testdir = os.path.dirname(os.path.abspath(__file__)) + os.path.sep

def _verify_planet_location(data, true_location, true_flux=None, true_fwhm=None, thresholds=None, searchrad=None):
    """
    Helper function to verify the planet how we expect it to look in the data. Only
    need to pass the true params you want to test (will skip the other ones)

    Args:
        data: 2d data with fake planet ot test
        true_location: [x,y] locaiton where we expect the planet
        true_flux: expected peak flux of the planet
        true_fwhm: expected fwhm on the plnaet
        thresholds: error tresholds. Need to pass all 4 even if not testing all of them
                    format is [xerr, yerr, fluxerr (Fractional), fwhmerr]
                    if None, threshold = [0.001, 0.001, 0.005, 0.05]
        searchrad: search radius for the fit
    """
    if thresholds is None:
        thresholds = [0.001, 0.001, 0.005, 0.05]
    elif np.size(thresholds) != 4:
        raise ValueError("thresholds should be a 4 element array but got {0} elements".format(np.size(thresholds)))
    if searchrad is None:
        if true_fwhm is not None:
            searchrad = int(round(true_fwhm))
        else:
            searchrad = 7
    
    rounded_true_location = np.rint(true_location)
    retrieved_noshift = fakes.gaussfit2d(data, rounded_true_location[0], rounded_true_location[1], searchrad=searchrad)
    output_noshift_pos = np.array(retrieved_noshift[2:4]) # [x, y]
    output_noshift_flux = retrieved_noshift[0]
    output_noshift_fwhm = retrieved_noshift[1]
    print(retrieved_noshift)
    # x position should be accurate to < 0.001 pixels
    assert np.abs(true_location[0] - output_noshift_pos[0]) < thresholds[0]
    # do the same for y position
    assert np.abs(true_location[1] - output_noshift_pos[1]) < thresholds[1]
    if true_flux is not None:
        # Flux without noise should be accurate to < 0.5%
        assert np.abs(true_flux - output_noshift_flux)/true_flux < thresholds[2]
    if true_fwhm is not None:
        # FWHM should also be accurate to within 0.05 pix
        assert np.abs(true_fwhm - output_noshift_fwhm) < thresholds[3]


def test_transform_and_centroding():
    """
    Tests the inject and retrieve planet functions on noiseless data
    with Gaussian planets. Also tests the align_and_scale
    routines in the cases when align and scale happen at the same time
    """
    # make a blank 281 x 281 canvas
    dat = np.zeros([281, 281]) 

    # inject a point source into it
    input_pos = [140, 140] # [x, y]
    input_flux = 1
    input_fwhm = 3.5
    injected = fakes._inject_gaussian_planet(dat, input_pos[0], input_pos[1], input_flux, input_fwhm)

    # make usre something is injected
    assert np.mean(injected) > 0

    # measure it to make sure it's in the right position
    thresholds = [0.001, 0.001, 0.005, 0.05]
    _verify_planet_location(dat, input_pos, input_flux, input_fwhm, thresholds)

    # now let's shift the image
    shift = 19.6 # in both x and y
    scale_factor = 2 # magnify image by a factor of 2
    new_pos = np.array(input_pos) + shift
    shifted = klip.align_and_scale(injected, new_pos, input_pos, scale_factor)

    # measure it to make sure it's in the right position
    _verify_planet_location(shifted, new_pos, input_flux, input_fwhm*scale_factor, thresholds)

def test_transform_and_centroding_with_custom_PSF():
    """
    Like test_transform_and_centroding, but with a custom PSF stamp
    """
    # make a blank 281 x 281 canvas
    dat = np.zeros([281, 281])

    # inject a point source into it
    input_pos = [140, 140] # [x, y]
    input_flux = 1
    input_fwhm = 3.5
    input_sigma = input_fwhm/(2.*np.sqrt(2*np.log(2)))
    # create a gaussian PSF stamp
    stampsize = 21
    y, x = np.indices([stampsize, stampsize], dtype=float)
    x -= stampsize//2
    y -= stampsize//2
    stamp = input_flux * np.exp(-(x**2 + y**2)/(2 * input_sigma**2))
    # hack it to inject planet at 0 separation at the center of the image
    fakes.inject_planet([dat], [input_pos], [stamp], [None], 0, 0, thetas=[0])

    # make usre something is injected
    assert np.mean(dat) > 0

    # measure it to make sure it's in the right position
    thresholds = [0.001, 0.001, 0.005, 0.05]
    _verify_planet_location(dat, input_pos, input_flux, input_fwhm, thresholds)

    # now let's shift the image
    shift = 19.6 # in both x and y
    scale_factor = 2 # magnify image by a factor of 2
    new_pos = np.array(input_pos) + shift
    shifted = klip.align_and_scale(dat, new_pos, input_pos, scale_factor)

    # measure it to make sure it's in the right position
    _verify_planet_location(shifted, new_pos, input_flux, input_fwhm*scale_factor, thresholds)


def test_rotate_with_centroiding():
    """
    Tests rotation. Both a 45 degree rotation, then another rotation with
    x flipped afterwards and shifted to a new center
    """
    # make a blank 281 x 281 canvas
    dat = np.zeros([281, 281]) 

    # inject a point source into it
    input_pos = [180, 140] # [x, y]
    input_flux = 1
    input_fwhm = 4
    injected = fakes._inject_gaussian_planet(dat, input_pos[0], input_pos[1], input_flux, input_fwhm)

    # make sure something is injected
    assert np.mean(injected) > 0

    # measure it to make sure it's in the right position
    thresholds = [0.001, 0.001, 0.005, 0.05]
    _verify_planet_location(dat, input_pos, input_flux, input_fwhm, thresholds)

    # define an image center
    center = np.array([140, 140])
    dxy_orig = np.array(input_pos) - center # delta x/y of planet

    # now let's rotate the image 45 degrees CCW
    rotang1 = 45 # degrees
    # transform dxy_orig to get what we expet the answer to be
    rotang1_radians = rotang1 * np.pi / 180.
    rot1_matrix = [[np.cos(rotang1_radians), -np.sin(rotang1_radians)], [np.sin(rotang1_radians), np.cos(rotang1_radians)]]
    dxy_1 =  np.dot(rot1_matrix, dxy_orig)
    rot1_pos = dxy_1 + center # new location of planet after rotation

    # do the actual rotation
    rotated1 = klip.rotate(injected, rotang1, center, flipx=False)

    # measure it to make sure it's in the right position
    thresholds = [0.001, 0.001, 0.005, 0.05]
    _verify_planet_location(rotated1, rot1_pos, input_flux, input_fwhm, thresholds)

    # now rotate again, but move the center and flip x 
    rotang2 = -185
    new_center = np.array([102.4,180.5])

    # now figure out where it should be
    # rotate the image
    rotang2_radians = rotang2 * np.pi / 180.
    rot2_matrix = [[np.cos(rotang2_radians), -np.sin(rotang2_radians)], [np.sin(rotang2_radians), np.cos(rotang2_radians)]]
    dxy_2 = np.dot(rot2_matrix, dxy_1)
    # flip x
    dxy_2[0] = -dxy_2[0]
    # recenter on new center
    rot2_pos = dxy_2 + new_center

    # do the actual rotation
    rotated2 = klip.rotate(rotated1, rotang2, center, new_center=new_center, flipx=True)

    # measure to make sure it's in the right position again
    _verify_planet_location(rotated2, rot2_pos, input_flux, input_fwhm, thresholds)


def test_estimate_movement():
    """
    This is essentially a unit test for estimate_movement
    """
    # test just azimuthal movement 
    radius = 50
    parang0 = 0
    parangs = np.array([0, 90, 180])
    true_moves = np.array([0, 50*math.sqrt(2), 100])
    calc_moves = klip.estimate_movement(radius, parang0=parang0, parangs=parangs)

    assert np.any(np.abs(true_moves - calc_moves) < 0.001)

    # test radial movement
    wv0 = 1
    wvs = np.array([0.5,1,1.5])
    true_moves = np.array([25, 0, 25])
    calc_moves = klip.estimate_movement(radius, wavelength0=wv0, wavelengths=wvs)
    
    assert np.any(np.abs(true_moves - calc_moves) < 0.001)

def test_annuli_bounds():
    """
    This tests the annuli bound selection code
    """
    annuli = 9
    iwa = 8
    owa = 100
    constant_bounds = klip.define_annuli_bounds(annuli, iwa, owa, "constant")

    # for constant spacing, we should get some sanity
    assert np.shape(constant_bounds) == (annuli, 2)
    assert constant_bounds[0][1]-constant_bounds[0][0] == float(owa-iwa)/annuli

    # test too many annuli exception
    caught_exception = False
    try:
        bounds = klip.define_annuli_bounds(owa+iwa+1, iwa, owa, "linear")
    except ValueError as e:
        caught_exception = True
    # check to make sure we got an exceptoin
    assert caught_exception


    # test log spacing works
    log_bounds = klip.define_annuli_bounds(annuli, iwa, owa, "log")
    log_bound_widths = np.diff(log_bounds, axis=1)
    # log bounds should be strictly increasing
    assert np.all(np.diff(log_bound_widths) > 0)


def test_meas_contrast():
    """
    Test the klip.meas_contrast function

    """
    # create a canvas
    y, x = np.indices([201,201])
    center = [100, 100]
    r = np.sqrt((x-center[0])**2 + (y-center[1])**2)

    # draw some random numbers
    rand_data = np.random.standard_normal(r.shape)
    # scale random by the distance to the star
    rand_data *= 1./(r**3)

    # bounds
    iwa = 10 # pixels
    owa = 70 # pixels
    # mask "coronagraph"
    rand_data[np.where(r < iwa)] = np.nan
    # create a square mask at the outer bondaries
    outer_nans = np.where((np.abs(x - center[0]) >= owa - 10) | np.abs(y - center[1]) >= owa - 10)
    rand_data[outer_nans] = np.nan

    seps, contrast = klip.meas_contrast(rand_data, iwa, owa, 3, center=center)

    closer_contrast = contrast[0]
    for c in contrast[1:]:
        # assert is less than previous closer in contrast, or at least within 20%
        assert(closer_contrast - c > -(0.2*closer_contrast))
        closer_contrast = c

    # also test other data inputs for low_pass_filter in measure contrast
    seps, contrast2 = klip.meas_contrast(rand_data, iwa, owa, 3, center=center, low_pass_filter=False)
    seps, contrast3 = klip.meas_contrast(rand_data, iwa, owa, 3, center=center, low_pass_filter=1)

    # they shouldn't be the same as the original
    assert contrast2[0] != contrast[0]
    assert contrast3[0] != contrast[0]


def test_airy_fit():
    """
    Test the fakes.airyfit2d function
    """
    y, x = np.indices([281,281])

    # truth values
    x0 = 131.4
    y0 = 151.9
    flux0 = 1.4
    fwhm0 = 3.2

    # inject data into frame
    airy_psf = modeling.functional_models.AiryDisk2D()
    data = airy_psf.evaluate(x, y, flux0, x0, y0, fwhm0/2.)

    # fit it
    fitflux, fitfwhm, fitx, fity = fakes.airyfit2d(data, int(x0), int(y0), searchrad=10)

    threshold = 1e-4
    assert x0 == pytest.approx(fitx, threshold)
    assert y0 == pytest.approx(fity, threshold)
    assert flux0 == pytest.approx(fitflux, threshold)
    assert fwhm0 == pytest.approx(fitfwhm, threshold)

def test_nair():
    """
    Test index of refraction code
    """
    n0 = nair.nMathar(1.5, 61400, 273, 0)

    n0 = nair.nMathar(3.39, 101325, 273.15+20, 56.98)
    assert np.abs(n0 - 1.00026740+ 1.75e-8) < 3e-8


def test_field_dependent_correction():
    """
    Test the field dependent correction in fakes.inject_planet() 
    """
    def correction(input_stamp, dx_stamp, dy_stamp):
        output_stamp = input_stamp * np.abs(dx_stamp) * np.abs(dy_stamp/2)
        return output_stamp

    psf = np.ones([1, 101, 101])
    test_img = np.zeros([1, 101, 101])
    centers = np.array([[50, 50]])
    fakes.inject_planet(test_img, centers, psf, None, 0, 0, thetas=np.array([0]),
                        field_dependent_correction=correction)

    print(test_img[0, 50, 50], test_img[0, 0, 0])
    # center of the image should have no throughput
    assert test_img[0, 50, 50] == pytest.approx(0, 1e-8)
    # edge of field is artifically enhanced
    assert test_img[0, 0, 0] == pytest.approx(50 * 25, 1e-8)

    # try it for a Gaussian now
    test_img = np.zeros([1, 101, 101])
    centers = np.array([[50, 50]])
    fakes.inject_planet(test_img, centers, np.array([1]), None, 0, 0, thetas=np.array([0]),
                        field_dependent_correction=correction)
    # we should have injected data into the image
    assert np.size(np.where(test_img != 0)) > 0
    # center of field should have no throughput
    assert test_img[0, 50, 50] == pytest.approx(0, 1e-8)


def test_wcs_generation():
    """
    Tests the code to generate WCS coordinate headers
    """
    # generate a zero image
    test_img = np.zeros([101, 101])

    parang = 80 # 90 degree rotation
    flipx = False # lefthanded
    center = [50, 50]

    wcs = wcsgen.generate_wcs(parang, center, flipx=flipx)

    # inject planet at PA of 45 degrees. Before the 90 degree rotation, it should be in +x/+y space. 
    fakes.inject_planet(test_img.reshape([1, 101, 101]), np.array([center]), np.array([1]), [wcs], 20, 45, fwhm=3)

    ymax, xmax = np.unravel_index(np.argmax(test_img), test_img.shape)
    assert xmax > 50
    assert ymax > 50

    dataset = Instrument.GenericData(np.array([test_img, test_img]), np.array([center, center]), parangs=np.array([parang, parang]), flipx=flipx)
    parallelized.klip_dataset(dataset, outputdir=testdir, fileprefix="wcstest", algo='none', movement=0)

    with fits.open("{out}/{pre}-KLmodes-all.fits".format(out=testdir, pre="wcstest")) as hdulist:
        output_frame = hdulist[0].data
        ymax, xmax = np.unravel_index(np.nanargmax(output_frame), test_img.shape)
        assert xmax < 50
        assert ymax > 50

    # test right handed coordinate system
    test_img = np.zeros([101, 101])

    parang = 80 # 90 degree rotation
    flipx = True # lefthanded
    center = [50, 50]

    wcs = wcsgen.generate_wcs(parang, center, flipx=flipx)

    # inject planet at PA of 45 degrees. Before the 90 degree rotation and flipping, it should be in +x/-y space. 
    fakes.inject_planet(test_img.reshape([1, 101, 101]), np.array([center]), np.array([1]), [wcs], 20, 45, fwhm=3)

    ymax, xmax = np.unravel_index(np.argmax(test_img), test_img.shape)
    assert xmax > 50
    assert ymax < 50

    dataset = Instrument.GenericData(np.array([test_img, test_img]), np.array([center, center]), parangs=np.array([parang, parang]), flipx=flipx)
    parallelized.klip_dataset(dataset, outputdir=testdir, fileprefix="wcstest_flipped", algo='none', movement=0)
    
    with fits.open("{out}/{pre}-KLmodes-all.fits".format(out=testdir, pre="wcstest_flipped")) as hdulist:
        output_frame = hdulist[0].data
        ymax, xmax = np.unravel_index(np.nanargmax(output_frame), test_img.shape)
        assert xmax < 50
        assert ymax > 50


def test_nan_gaussian_filter():
    """
    Tests that nan gaussian filter smooths the data and that it preserves flux
    """
    # should reduce pixel to pixel noise
    noise_img = np.random.random((100, 100))
    std_before = np.std(noise_img)
    smoothed_img = klip.nan_gaussian_filter(noise_img, 1)
    std_after = np.std(smoothed_img)
    assert std_before > std_after

    # check flux perservation
    const_img = np.ones((100, 100))
    smoothed_const_img = klip.nan_gaussian_filter(const_img, 1)
    assert np.all(smoothed_const_img == const_img)

if __name__ == "__main__":
    test_nan_gaussian_filter()
