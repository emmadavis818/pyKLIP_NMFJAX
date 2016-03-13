__author__ = 'jruffio'
import multiprocessing as mp
import ctypes

import numpy as np
import pyklip.spectra_management as specmanage
import os

from pyklip.fmlib.nofm import NoFM
import pyklip.fm as fm

from scipy import interpolate
from copy import copy

#import matplotlib.pyplot as plt
debug = False


class ExtractSpec(NoFM):
    """
    Planet Characterization class. Goal to characterize the astrometry and photometry of a planet
    """
    def __init__(self, inputs_shape,
                 numbasis,
                 sep, pa, dflux,
                 input_psfs,
                 input_psfs_wvs,
                 flux_conversion,
                 wavelengths='H',
                 spectrallib=None,
                 star_spt=None,
                 datatype="float",
                 stamp_size = None):
        """
        Defining the planet to characterizae

        Args:
            inputs_shape: shape of the inputs numpy array. Typically (N, y, x)
            numbasis: 1d numpy array consisting of the number of basis vectors to use
            sep: separation of the planet
            pa: position angle of the planet
            dflux: guess for delta flux of planet averaged across band w.r.t star
            input_psfs: the psf of the image. A numpy array with shape (wv, y, x)
            input_psfs_wvs: the wavelegnths that correspond to the input psfs
            flux_conversion: an array of length N to convert from contrast to DN for each frame. Units of DN/contrast
            wavelengths: wavelengths of data. Can just be a string like 'H' for H-band
            spectrallib: if not None, a list of spectra
            star_spt: star spectral type, if None default to some random one
            refine_fit: refine the separation and pa supplied
        """
        # allocate super class
        super(ExtractSpec, self).__init__(inputs_shape, np.array(numbasis))

        if stamp_size is None:
            self.stamp_size = 10
        else:
            self.stamp_size = stamp_size

        if datatype=="double":
            self.mp_data_type = ctypes.c_double
            self.np_data_type = float
        elif datatype=="float":
            self.mp_data_type = ctypes.c_float
            self.np_data_type = np.float32

        self.N_numbasis =  np.size(numbasis)
        self.ny = self.inputs_shape[1]
        self.nx = self.inputs_shape[2]
        self.N_frames = self.inputs_shape[0]

        self.inputs_shape = inputs_shape
        self.numbasis = numbasis
        self.sep = sep
        self.pa = pa


        self.input_psfs = input_psfs
        self.input_psfs_wvs = list(np.array(input_psfs_wvs,dtype=self.np_data_type))
        self.nl = np.size(input_psfs_wvs)
        #self.flux_conversion = flux_conversion
        self.input_psfs = input_psfs
        # Make sure the peak value is unity for all wavelengths
        self.sat_spot_spec = np.nanmax(self.input_psfs,axis=(1,2))
        for l_id in range(self.input_psfs.shape[0]):
            self.input_psfs[l_id,:,:] /= self.sat_spot_spec[l_id]

        self.nl, self.ny_psf, self.nx_psf =  self.input_psfs.shape

        self.psf_centx_notscaled = {}
        self.psf_centy_notscaled = {}

        numwv,ny_psf,nx_psf =  self.input_psfs.shape
        x_psf_grid, y_psf_grid = np.meshgrid(np.arange(ny_psf* 1.)-ny_psf/2, np.arange(nx_psf * 1.)-nx_psf/2)
        psfs_func_list = []
        for wv_index in range(numwv):
            model_psf = self.input_psfs[wv_index, :, :] #* self.flux_conversion * self.spectrallib[0][wv_index] * self.dflux
            psfs_func_list.append(interpolate.LSQBivariateSpline(x_psf_grid.ravel(),y_psf_grid.ravel(),model_psf.ravel(),x_psf_grid[0,0:nx_psf-1]+0.5,y_psf_grid[0:ny_psf-1,0]+0.5))

        self.psfs_func_list = psfs_func_list


    # def alloc_interm(self, max_sector_size, numsciframes):
    #     """Allocates shared memory array for intermediate step
    #
    #     Intermediate step is allocated for a sector by sector basis
    #
    #     Args:
    #         max_sector_size: number of pixels in this sector. Max because this can be variable. Stupid rotating sectors
    #
    #     Returns:
    #         interm: mp.array to store intermediate products from one sector in
    #         interm_shape:shape of interm array (used to convert to numpy arrays)
    #
    #     """
    #
    #     interm_size = max_sector_size * np.size(self.numbasis) * numsciframes * len(self.spectrallib)
    #
    #     interm = mp.Array(ctypes.c_double, interm_size)
    #     interm_shape = [numsciframes, len(self.spectrallib), max_sector_size, np.size(self.numbasis)]
    #
    #     return interm, interm_shape


    def alloc_fmout(self, output_img_shape):
        """Allocates shared memory for the output of the shared memory


        Args:
            output_img_shape: shape of output image (usually N,y,x,b)

        Returns:
            fmout: mp.array to store FM data in
            fmout_shape: shape of FM data array

        """
        # The 3rd dimension (self.N_frames corresponds to the spectrum)
        # The +1 in (self.N_frames+1) is for the klipped image
        fmout_size = self.N_numbasis*self.N_frames*(self.N_frames+1)*self.stamp_size*self.stamp_size
        fmout = mp.Array(self.mp_data_type, fmout_size)
        fmout_shape = (self.N_numbasis,self.N_frames,(self.N_frames+1),self.stamp_size*self.stamp_size )

        return fmout, fmout_shape


    # def alloc_perturbmag(self, output_img_shape, numbasis):
    #     """
    #     Allocates shared memory to store the fractional magnitude of the linear KLIP perturbation
    #     Stores a number for each frame = max(oversub + selfsub)/std(PCA(image))
    #
    #     Args:
    #         output_img_shape: shape of output image (usually N,y,x,b)
    #         numbasis: array/list of number of KL basis cutoffs requested
    #
    #     Returns:
    #         perturbmag: mp.array to store linaer perturbation magnitude
    #         perturbmag_shape: shape of linear perturbation magnitude
    #
    #     """
    #     perturbmag_shape = (output_img_shape[0], np.size(numbasis))
    #     perturbmag = mp.Array(ctypes.c_double, np.prod(perturbmag_shape))
    #
    #     return perturbmag, perturbmag_shape


    def generate_models(self, input_img_shape, section_ind, pas, wvs, radstart, radend, phistart, phiend, padding, ref_center, parang, ref_wv,stamp_size = None):
        """
        Generate model PSFs at the correct location of this segment for each image denoated by its wv and parallactic angle

        Args:
            pas: array of N parallactic angles corresponding to N images [degrees]
            wvs: array of N wavelengths of those images
            radstart: radius of start of segment
            radend: radius of end of segment
            phistart: azimuthal start of segment [radians]
            phiend: azimuthal end of segment [radians]
            padding: amount of padding on each side of sector
            ref_center: center of image
            parang: parallactic angle of input image [DEGREES]
            ref_wv: wavelength of science image
            stamp_size: size of the stamp for spectral extraction

        Return:
            models: array of size (N, p) where p is the number of pixels in the segment
        """
        # create some parameters for a blank canvas to draw psfs on
        nx = input_img_shape[1]
        ny = input_img_shape[0]
        x_grid, y_grid = np.meshgrid(np.arange(nx * 1.)-ref_center[0], np.arange(ny * 1.)-ref_center[1])


        numwv, ny_psf, nx_psf =  self.input_psfs.shape

        # create bounds for PSF stamp size
        row_m = np.floor(ny_psf/2.0)    # row_minus
        row_p = np.ceil(ny_psf/2.0)     # row_plus
        col_m = np.floor(nx_psf/2.0)    # col_minus
        col_p = np.ceil(nx_psf/2.0)     # col_plus

        if stamp_size is not None:
            stamp_mask = np.zeros((ny,nx))
            # create bounds for spectral extraction stamp size
            row_m_stamp = np.floor(stamp_size/2.0)    # row_minus
            row_p_stamp = np.ceil(stamp_size/2.0)     # row_plus
            col_m_stamp = np.floor(stamp_size/2.0)    # col_minus
            col_p_stamp = np.ceil(stamp_size/2.0)     # col_plus
            stamp_indices=[]

        # a blank img array of write model PSFs into
        whiteboard = np.zeros((ny,nx))
        if debug:
            canvases = []
        models = []
        #print(self.input_psfs.shape)
        for pa, wv in zip(pas, wvs):
            #print(self.pa,self.sep)
            #print(pa,wv)
            # grab PSF given wavelength
            wv_index = np.where(wv == self.input_psfs_wvs)[0]
            #model_psf = self.input_psfs[wv_index[0], :, :] #* self.flux_conversion * self.spectrallib[0][wv_index] * self.dflux

            # find center of psf
            # to reduce calculation of sin and cos, see if it has already been calculated before
            if pa not in self.psf_centx_notscaled:
                self.psf_centx_notscaled[pa] = self.sep * np.cos(np.radians(90. - self.pa - pa))
                self.psf_centy_notscaled[pa] = self.sep * np.sin(np.radians(90. - self.pa - pa))
            psf_centx = (ref_wv/wv) * self.psf_centx_notscaled[pa]
            psf_centy = (ref_wv/wv) * self.psf_centy_notscaled[pa]

            # create a coordinate system for the image that is with respect to the model PSF
            # round to nearest pixel and add offset for center
            l = round(psf_centx + ref_center[0])
            k = round(psf_centy + ref_center[1])
            # recenter coordinate system about the location of the planet
            x_vec_stamp_centered = x_grid[0, (l-col_m):(l+col_p)]-psf_centx
            y_vec_stamp_centered = y_grid[(k-row_m):(k+row_p), 0]-psf_centy
            # rescale to account for the align and scaling of the refernce PSFs
            # e.g. for longer wvs, the PSF has shrunk, so we need to shrink the coordinate system
            x_vec_stamp_centered /= (ref_wv/wv)
            y_vec_stamp_centered /= (ref_wv/wv)

            # use intepolation spline to generate a model PSF and write to temp img
            whiteboard[(k-row_m):(k+row_p), (l-col_m):(l+col_p)] = \
                    self.psfs_func_list[wv_index[0]](x_vec_stamp_centered,y_vec_stamp_centered)

            # write model img to output (segment is collapsed in x/y so need to reshape)
            whiteboard.shape = [input_img_shape[0] * input_img_shape[1]]
            segment_with_model = copy(whiteboard[section_ind])
            whiteboard.shape = [input_img_shape[0],input_img_shape[1]]

            models.append(segment_with_model)

            if stamp_size is not None:
                # These are actually indices of indices. they indicate which indices correspond to the stamp in section_ind
                stamp_mask[(k-row_m_stamp):(k+row_p_stamp), (l-col_m_stamp):(l+col_p_stamp)] = 1
                stamp_mask.shape = [nx*ny]
                stamp_indices.append(np.where(stamp_mask[section_ind] == 1)[0])
                stamp_mask.shape = [ny,nx]
                stamp_mask[(k-row_m_stamp):(k+row_p_stamp), (l-col_m_stamp):(l+col_p_stamp)] = 0

        if stamp_size is not None:
            return np.array(models),stamp_indices
        else:
            return np.array(models)




    def fm_from_eigen(self, klmodes=None, evals=None, evecs=None, input_img_shape=None, input_img_num=None, ref_psfs_indicies=None, section_ind=None, aligned_imgs=None, pas=None,
                     wvs=None, radstart=None, radend=None, phistart=None, phiend=None, padding=None,IOWA = None, ref_center=None,
                     parang=None, ref_wv=None, numbasis=None, fmout=None, perturbmag=None, klipped=None, **kwargs):
        """
        Generate forward models using the KL modes, eigenvectors, and eigenvectors from KLIP. Calls fm.py functions to
        perform the forward modelling

        Args:
            klmodes: unpertrubed KL modes
            evals: eigenvalues of the covariance matrix that generated the KL modes in ascending order
                   (lambda_0 is the 0 index) (shape of [nummaxKL])
            evecs: corresponding eigenvectors (shape of [p, nummaxKL])
            input_image_shape: 2-D shape of inpt images ([ysize, xsize])
            input_img_num: index of sciece frame
            ref_psfs_indicies: array of indicies for each reference PSF
            section_ind: array indicies into the 2-D x-y image that correspond to this section.
                         Note needs be called as section_ind[0]
            pas: array of N parallactic angles corresponding to N reference images [degrees]
            wvs: array of N wavelengths of those referebce images
            radstart: radius of start of segment
            radend: radius of end of segment
            phistart: azimuthal start of segment [radians]
            phiend: azimuthal end of segment [radians]
            padding: amount of padding on each side of sector
            IOWA: tuple (IWA,OWA) where IWA = Inner working angle and OWA = Outer working angle both in pixels.
                It defines the separation interva in which klip will be run.
            ref_center: center of image
            numbasis: array of KL basis cutoffs
            parang: parallactic angle of input image [DEGREES]
            ref_wv: wavelength of science image
            fmout: numpy output array for FM output. Shape is (N, y, x, b)
            perturbmag: numpy output for size of linear perturbation. Shape is (N, b)
            klipped: PSF subtracted image. Shape of ( size(section), b)
            kwargs: any other variables that we don't use but are part of the input
        """
        sci = aligned_imgs[input_img_num, section_ind[0]]
        refs = aligned_imgs[ref_psfs_indicies, :]
        refs = refs[:, section_ind[0]]


        # generate models for the PSF of the science image
        model_sci, stamp_indices = self.generate_models(input_img_shape, section_ind, [parang], [ref_wv], radstart, radend, phistart, phiend, padding, ref_center, parang, ref_wv,stamp_size=self.stamp_size)
        model_sci = model_sci[0]
        stamp_indices = stamp_indices[0]
        #model_sci *= self.flux_conversion[input_img_num] * self.spectrallib[0][np.where(self.input_psfs_wvs == ref_wv)] * self.dflux

        # generate models of the PSF for each reference segments. Output is of shape (N, pix_in_segment)
        models_ref = self.generate_models(input_img_shape, section_ind, pas, wvs, radstart, radend, phistart, phiend, padding, ref_center, parang, ref_wv)

        # using original Kl modes and reference models, compute the perturbed KL modes (spectra is already in models)
        #delta_KL = fm.perturb_specIncluded(evals, evecs, klmodes, refs, models_ref)
        delta_KL_nospec = fm.pertrurb_nospec(evals, evecs, klmodes, refs, models_ref)

        # calculate postklip_psf using delta_KL
        oversubtraction, selfsubtraction = fm.calculate_fm(delta_KL_nospec, klmodes, numbasis, sci, model_sci, inputflux=None)
        # klipped_oversub.shape = (size(numbasis),Npix)
        # klipped_selfsub.shape = (size(numbasis),N_lambda or N_ref,N_pix)
        # klipped_oversub = Sum(<S|KL>KL)
        # klipped_selfsub = Sum(<N|DKL>KL) + Sum(<N|KL>DKL)

        # # write forward modelled PSF to fmout (as output)
        # # need to derotate the image in this step
        # for thisnumbasisindex in range(np.size(numbasis)):
        #         fm._save_rotated_section(input_img_shape, postklip_psf[thisnumbasisindex], section_ind,
        #                          fmout[input_img_num, :, :,thisnumbasisindex], None, parang,
        #                          radstart, radend, phistart, phiend, padding,IOWA, ref_center, flipx=True)


        #input_img_num=None, ref_psfs_indicies=None, section_ind[stamp_indices]=None
        # fmout.shape (self.N_numbasis,self.N_frames,(self.N_frames+1),self.stamp_size*self.stamp_size)
        for k in range(self.N_numbasis):
            fmout[k,input_img_num, input_img_num,:] = model_sci[stamp_indices]
        fmout[:,input_img_num, input_img_num,:] = -oversubtraction[:,stamp_indices]
        fmout[:,input_img_num, ref_psfs_indicies,:] = -selfsubtraction[:,:,stamp_indices]
        fmout[:,input_img_num, -1,:] = klipped.T[:,stamp_indices]




    def cleanup_fmout(self, fmout):
        """
        After running KLIP-FM, we need to reshape fmout so that the numKL dimension is the first one and not the last

        Args:
            fmout: numpy array of ouput of FM

        Return:
            fmout: same but cleaned up if necessary
        """
        # Here we actually extract the spectrum

        spec_identity = np.identity(37)
        selec = np.tile(spec_identity,(self.N_frames/self.nl,1))

        FM_noSpec = fmout[0,:, 0:self.N_frames,:]

        FM_noSpec = np.rollaxis(FM_noSpec,2,1)
        klipped = fmout[0,:, -1,:]

        FM_noSpec_mat = np.reshape(FM_noSpec,(self.N_frames*self.stamp_size*self.stamp_size,self.N_frames))
        klipped_vec = np.reshape(klipped,(self.N_frames*self.stamp_size*self.stamp_size,))

        print("coucou")
        print(FM_noSpec_mat.shape)
        print(klipped.shape)

        FM_noSpec_mat = np.dot(FM_noSpec_mat,selec)
        print("FM_noSpec_mat after selec",FM_noSpec_mat.shape)

        pinv_fm = np.linalg.pinv(FM_noSpec_mat)
        estim_spec = np.dot(pinv_fm,klipped_vec)
        print("pinv_fm",pinv_fm.shape)

        import matplotlib.pyplot as plt
        plt.plot(estim_spec)
        plt.show()

        return fmout



def calculate_annuli_bounds(num_annuli, annuli_index, iwa, firstframe, firstframe_centers):
    """
    Calculate annulus boundaries of a particular annuli. Useful for figuring out annuli boundaries when just giving an
    integer as the parameter to pyKLIP

    Args:
        num_annuli: integer for number of annuli requested
        annuli_index: integer for which annuli (innermost annulus is 0)
        iwa: inner working angle
        firstframe: data of first frame of the sequence. dataset.inputs[0]
        firstframe_centers: [x,y] center for the first frame. i.e. dataset.centers[0]

    Returns:
        rad_bounds[annuli_index]: radial separation of annuli. [annuli_start, annuli_end]
                                  This is a single 2 element list [annuli_start, annuli_end]
    """
    dims = firstframe.shape

    # use first image to figure out how to divide the annuli
    # TODO: what to do with OWA
    # need to make the next 10 lines or so much smarter

    x, y = np.meshgrid(np.arange(dims[1] * 1.0), np.arange(dims[0] * 1.0))
    nanpix = np.where(np.isnan(firstframe))

    owa = np.sqrt(np.min((x[nanpix] - firstframe_centers[0]) ** 2 + (y[nanpix] - firstframe_centers[1]) ** 2))

    dr = float(owa - iwa) / (num_annuli)
    # calculate the annuli
    rad_bounds = [(dr * rad + iwa, dr * (rad + 1) + iwa) for rad in range(num_annuli)]

    # return desired
    return rad_bounds[annuli_index]