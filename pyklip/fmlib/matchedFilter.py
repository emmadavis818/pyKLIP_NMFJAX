__author__ = 'jruffio'
import multiprocessing as mp
import ctypes

import numpy as np
import pyklip.spectra_management as specmanage
import os
import itertools

from pyklip.fmlib.nofm import NoFM
import pyklip.fm as fm

from scipy import interpolate
from copy import copy

import astropy.io.fits as pyfits

import matplotlib.pyplot as plt
debug = False


class MatchedFilter(NoFM):
    """
    Planet Characterization class. Goal to characterize the astrometry and photometry of a planet
    """
    def __init__(self, inputs_shape,numbasis, input_psfs,input_psfs_wvs, flux_conversion,
                 spectrallib = None,
                 mute = False,
                 star_type = None,
                 filter = None,
                 save_per_sector = None):
        # allocate super class
        super(MatchedFilter, self).__init__(inputs_shape, numbasis)

        if save_per_sector is not None:
            self.fmout_dir = save_per_sector
            self.save_fmout = True

        self.N_numbasis =  np.size(numbasis)
        self.ny = self.inputs_shape[1]
        self.nx = self.inputs_shape[2]
        self.N_frames = self.inputs_shape[0]

        if filter is None:
            filter = "H"

        if star_type is None:
            star_type = "G4"

        self.inputs_shape = self.inputs_shape
        if spectrallib is not None:
            self.spectrallib = spectrallib
        else:
            spectra_folder = os.path.dirname(os.path.abspath(specmanage.__file__)) + os.sep + "spectra" + os.sep
            spectra_files = [spectra_folder + "t650g18nc.flx"]
            self.spectrallib = [specmanage.get_planet_spectrum(filename, filter)[1] for filename in spectra_files]

        self.N_spectra = len(self.spectrallib)

        # TODO: calibrate to contrast units
        # calibrate spectra to DN
        self.spectrallib = [spectrum/(specmanage.get_star_spectrum(filter, star_type=star_type)[1]) for spectrum in self.spectrallib]
        self.spectrallib = [spectrum/np.mean(spectrum) for spectrum in self.spectrallib]

        self.input_psfs_wvs = input_psfs_wvs
        self.nl = np.size(input_psfs_wvs)
        self.flux_conversion = flux_conversion
        self.input_psfs = input_psfs
        # Make sure the peak value is unity for all wavelengths
        self.sat_spot_spec = np.nanmax(self.input_psfs,axis=(1,2))
        for l_id in range(self.input_psfs.shape[0]):
            self.input_psfs[l_id,:,:] /= self.sat_spot_spec[l_id]


        self.psf_centx_notscaled = {}
        self.psf_centy_notscaled = {}
        self.curr_pa_fk = {}
        self.curr_sep_fk = {}

        numwv,ny_psf,nx_psf =  self.input_psfs.shape
        x_psf_grid, y_psf_grid = np.meshgrid(np.arange(ny_psf* 1.)-ny_psf/2, np.arange(nx_psf * 1.)-nx_psf/2)
        psfs_func_list = []
        for wv_index in range(numwv):
            model_psf = self.input_psfs[wv_index, :, :]
            psfs_func_list.append(interpolate.LSQBivariateSpline(x_psf_grid.ravel(),y_psf_grid.ravel(),model_psf.ravel(),x_psf_grid[0,0:nx_psf-1]+0.5,y_psf_grid[0:ny_psf-1,0]+0.5))

        self.psfs_func_list = psfs_func_list

        ny_PSF,nx_PSF = input_psfs.shape[1:]
        stamp_PSF_x_grid, stamp_PSF_y_grid = np.meshgrid(np.arange(0,nx_PSF,1)-nx_PSF/2,np.arange(0,ny_PSF,1)-ny_PSF/2)
        self.stamp_PSF_mask = np.ones((ny_PSF,nx_PSF))
        r_PSF_stamp = abs((stamp_PSF_x_grid) +(stamp_PSF_y_grid)*1j)
        self.stamp_PSF_mask[np.where(r_PSF_stamp < 3.)] = np.nan

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
            fmout: mp.array to store auxilliary data in
            fmout_shape: shape of auxilliary array

        """

        # The 3 is for saving the different term of the matched filter
        # 0: dot product
        # 1: square of the norm of the model
        # 2: square of the norm of the image
        fmout_size = 3*self.N_spectra*self.N_numbasis*self.N_frames*self.ny*self.nx
        fmout = mp.Array(ctypes.c_double, fmout_size)
        fmout_shape = (3,self.N_spectra,self.N_numbasis,self.N_frames,self.ny,self.nx)

        return fmout, fmout_shape


    def fm_from_eigen(self, klmodes=None, evals=None, evecs=None, input_img_shape=None, input_img_num=None, ref_psfs_indicies=None, section_ind=None, aligned_imgs=None, pas=None,
                     wvs=None, radstart=None, radend=None, phistart=None, phiend=None, padding=None,IOWA = None, ref_center=None,
                     parang=None, ref_wv=None, numbasis=None, fmout=None,klipped=None, **kwargs):
        """

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
            ref_center: center of image
            numbasis: array of KL basis cutoffs
            parang: parallactic angle of input image [DEGREES]
            ref_wv: wavelength of science image
            fmout: numpy output array for FM output. Shape is (N, y, x, b)
            klipped: array of shape (p,b) that is the PSF subtracted data for each of the b KLIP basis
                     cutoffs. If numbasis was an int, then sub_img_row_selected is just an array of length p
            kwargs: any other variables that we don't use but are part of the input
        """
        sci = aligned_imgs[input_img_num, section_ind[0]]
        refs = aligned_imgs[ref_psfs_indicies, :]
        refs = refs[:, section_ind[0]]

        # Calculate the PA,sep 2D map
        x_grid, y_grid = np.meshgrid(np.arange(self.nx * 1.0)- ref_center[0], np.arange(self.ny * 1.0)- ref_center[1])
        r_grid = np.sqrt((x_grid)**2 + (y_grid)**2)
        pa_grid = np.arctan2( -x_grid,y_grid) % (2.0 * np.pi)
        #pa_grid = np.arctan2( -y_grid,x_grid) % (2.0 * np.pi)
        # normal case where there's no 2 pi wrap
        #print(phistart/np.pi*180,phiend/np.pi*180)
        paend= ((2*np.pi-phistart +np.pi/2)% (2.0 * np.pi))
        pastart = ((2*np.pi-phiend +np.pi/2)% (2.0 * np.pi))
        #print(pastart/np.pi*180,paend/np.pi*180)
        if pastart < paend:
            where_section = np.where((r_grid >= radstart) & (r_grid < radend) & (pa_grid >= pastart) & (pa_grid < paend))
        # 2 pi wrap case
        else:
            where_section = np.where((r_grid >= radstart) & (r_grid < radend) & ((pa_grid >= pastart) | (pa_grid < paend)))
        # JB debug
        if 0:
            phi_grid = np.arctan2(y_grid , x_grid) % (2.0 * np.pi)
            print(parang)
            print(phistart/np.pi*180,phiend/np.pi*180)
            print(pastart/np.pi*180,paend/np.pi*180)
            print(pa_grid[where_section]/np.pi*180)
            print(r_grid[where_section])
            print(ref_center)
            r_grid[where_section] = 0.0
            pa_grid[where_section] = 0.0
            plt.subplot(121)
            plt.imshow(phi_grid)
            plt.colorbar()
            plt.subplot(122)
            plt.imshow(pa_grid)
            plt.colorbar()
            plt.show()

        # Get a list of the PAs and sep of the PA,sep map falling in the current section
        #where_section = where_section[0][::2]
        r_list = r_grid[where_section]
        pa_list = pa_grid[where_section]
        #r_list = r_list[::10]
        #pa_list = pa_list[::10]

        # For all PAs and sep
        N_tot_it = self.N_spectra*self.N_numbasis*np.size(r_list)
        #N_it = 0
        for spec_id,N_KL_id in itertools.product(range(self.N_spectra),range(self.N_numbasis)):
            for sep_fk,pa_fk,row_id,col_id in zip(r_list,np.rad2deg(pa_list),where_section[0],where_section[1]):
                #print(sep_fk,pa_fk,r_grid[row_id,col_id],pa_grid[row_id,col_id]/np.pi*180)
                #N_it = N_it + 1
                #print(N_it,N_tot_it,float(N_it)/float(N_tot_it))
                #   Generate model sci
                model_sci,mask = self.generate_model_sci(input_img_shape, section_ind, parang, ref_wv, radstart, radend, phistart, phiend, padding, ref_center, parang, ref_wv,sep_fk,pa_fk)#32.,170.)#sep_fk,pa_fk)
                model_sci *= self.flux_conversion[input_img_num] * self.spectrallib[spec_id][np.where(self.input_psfs_wvs == ref_wv)]*1e-5
                where_fk = np.where(mask>=1)[0]
                where_background = np.where(mask==2)[0]
                #print(model_sci[where_fk])
                #   Generate models ref
                models_ref = self.generate_models(input_img_shape, section_ind, pas, wvs, radstart, radend, phistart, phiend, padding, ref_center, parang, ref_wv,sep_fk,pa_fk)#32.,170.)#,sep_fk,pa_fk)
                #print(models_ref[0][where_fk])
                # Calculate the spectra to determine the flux of each model reference PSF
                total_imgs = np.size(self.flux_conversion)
                input_spectrum =  self.spectrallib[spec_id]
                input_spectrum = self.flux_conversion * np.ravel(np.tile(input_spectrum,(1, total_imgs/self.nl)))*1e-5
                input_spectrum = input_spectrum[ref_psfs_indicies]
                models_ref = models_ref * input_spectrum[:, None]

                # using original Kl modes and reference models, compute the perturbed KL modes (spectra is already in models)
                delta_KL = fm.perturb_specIncluded(evals, evecs, klmodes, refs, models_ref)

                # calculate postklip_psf using delta_KL
                #print(model_sci[where_fk])
                #print(delta_KL)
                postklip_psf, oversubtraction, selfsubtraction = fm.calculate_fm(delta_KL, klmodes, numbasis, sci, model_sci, inputflux=None)

                #print(klipped[:,N_KL_id].shape,postklip_psf[N_KL_id,:].shape)


                if 0:
                    blackboard1 = np.zeros((self.ny,self.nx))
                    blackboard2 = np.zeros((self.ny,self.nx))
                    blackboard3 = np.zeros((self.ny,self.nx))
                    #print(section_ind)
                    plt.figure(1)
                    plt.subplot(1,3,1)
                    blackboard1.shape = [input_img_shape[0] * input_img_shape[1]]
                    blackboard1[section_ind] = mask
                    blackboard1.shape = [input_img_shape[0],input_img_shape[1]]
                    plt.imshow(blackboard1)
                    plt.colorbar()
                    plt.subplot(1,3,2)
                    blackboard2.shape = [input_img_shape[0] * input_img_shape[1]]
                    blackboard2[section_ind[0][where_fk]] = klipped[where_fk,N_KL_id]
                    blackboard2.shape = [input_img_shape[0],input_img_shape[1]]
                    plt.imshow(blackboard2)
                    plt.colorbar()
                    plt.subplot(1,3,3)
                    blackboard3.shape = [input_img_shape[0] * input_img_shape[1]]
                    blackboard3[section_ind[0][where_fk]] = postklip_psf[N_KL_id,where_fk]
                    blackboard3.shape = [input_img_shape[0],input_img_shape[1]]
                    plt.imshow(blackboard3)
                    plt.colorbar()
                    #print(klipped[where_fk,N_KL_id])
                    #print(postklip_psf[N_KL_id,where_fk])
                    print(np.sum(klipped[where_fk,N_KL_id]*postklip_psf[N_KL_id,where_fk]))
                    print(np.sum(postklip_psf[N_KL_id,where_fk]*postklip_psf[N_KL_id,where_fk]))
                    print(np.sum(klipped[where_fk,N_KL_id]*klipped[where_fk,N_KL_id]))
                    plt.show()
                # 0: dot product
                # 1: square of the norm of the model
                # 2: square of the norm of the image
                #fmout_shape = (3,self.N_spectra,self.N_numbasis,self.N_frames,self.ny,self.nx)
                sky = np.mean(klipped[where_background,N_KL_id])
                klipped_sub = klipped[where_fk,N_KL_id]-sky
                fmout[0,spec_id,N_KL_id,input_img_num,row_id,col_id] = np.sum(klipped_sub*postklip_psf[N_KL_id,where_fk])
                fmout[1,spec_id,N_KL_id,input_img_num,row_id,col_id] = np.sum(postklip_psf[N_KL_id,where_fk]*postklip_psf[N_KL_id,where_fk])
                fmout[2,spec_id,N_KL_id,input_img_num,row_id,col_id] = np.sum(klipped_sub*klipped_sub)

        #plt.imshow(np.squeeze(fmout[0,spec_id,N_KL_id,input_img_num,:,:]))
        #plt.show()



    def fm_end_sector(self, interm_data=None, fmout=None, sector_index=None,
                               section_indicies=None):
        """
        Does some forward modelling at the end of a sector after all images have been klipped for that sector.

        """

        #fmout_shape = (3,self.N_spectra,self.N_numbasis,self.N_frames,self.ny,self.nx)

        if self.save_fmout:
            hdu = pyfits.PrimaryHDU(fmout)
            hdulist = pyfits.HDUList([hdu])
            hdulist.writeto(self.fmout_dir,clobber=True)

        if 0:
            matched_filter_maps = np.nansum(fmout[0,:,:,:,:,:],axis=2)
            model_square_norm_maps = np.nansum(fmout[1,:,:,:,:,:],axis=2)
            image_square_norm_maps = np.nansum(fmout[2,:,:,:,:,:],axis=2)
            metric = matched_filter_maps/np.sqrt(model_square_norm_maps*image_square_norm_maps)
            metric = np.squeeze(metric[0,0,:,:])
                    #fmout_shape = (3,self.N_spectra,self.N_numbasis,self.N_frames,self.ny,self.nx)

            print(np.nanargmax(metric),np.nanmax(metric))

            plt.figure(1)
            plt.imshow(metric,interpolation="nearest")
            plt.colorbar()
            plt.show()

        return



    def generate_model_sci(self, input_img_shape, section_ind, pa, wv, radstart, radend, phistart, phiend, padding, ref_center, parang, ref_wv,sep_fk,pa_fk):
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

        # a blank img array of write model PSFs into
        whiteboard = np.zeros((ny,nx))
        #print(self.input_psfs.shape)
        #print(self.pa,self.sep)
        #print(pa,wv)
        # grab PSF given wavelength
        wv_index = np.where(wv == self.input_psfs_wvs)[0]
        #model_psf = self.input_psfs[wv_index[0], :, :] #* self.flux_conversion * self.spectrallib[0][wv_index] * self.dflux

        # find center of psf
        # to reduce calculation of sin and cos, see if it has already been calculated before

        recalculate_trig = False
        if pa not in self.psf_centx_notscaled:
            recalculate_trig = True
        else:
            if pa_fk != self.curr_pa_fk[pa] or sep_fk != self.curr_sep_fk[pa]:
                recalculate_trig = True
        if recalculate_trig: # we could actually store the values for the different pas too...
            self.psf_centx_notscaled[pa] = sep_fk * np.cos(np.radians(90. - pa_fk - pa))
            self.psf_centy_notscaled[pa] = sep_fk * np.sin(np.radians(90. - pa_fk - pa))
            self.curr_pa_fk[pa] = pa_fk
            self.curr_sep_fk[pa] = sep_fk

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

        # create a canvas to place the new PSF in the sector on
        if 0:
            blackboard = np.zeros((ny,nx))
            blackboard.shape = [input_img_shape[0] * input_img_shape[1]]
            blackboard[section_ind] = segment_with_model
            blackboard.shape = [input_img_shape[0],input_img_shape[1]]
            plt.figure(1)
            plt.subplot(1,2,1)
            im = plt.imshow(whiteboard)
            plt.colorbar(im)
            plt.subplot(1,2,2)
            im = plt.imshow(blackboard)
            plt.colorbar(im)
            plt.show()

        whiteboard[(k-row_m):(k+row_p), (l-col_m):(l+col_p)] = 1
        whiteboard[(k-row_m):(k+row_p), (l-col_m):(l+col_p)][np.where(np.isfinite(self.stamp_PSF_mask))]=2
        whiteboard.shape = [input_img_shape[0] * input_img_shape[1]]
        mask = whiteboard[section_ind]

        return segment_with_model,mask


    def generate_models(self, input_img_shape, section_ind, pas, wvs, radstart, radend, phistart, phiend, padding, ref_center, parang, ref_wv,sep_fk,pa_fk):
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

        # a blank img array of write model PSFs into
        whiteboard = np.zeros((ny,nx))
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
            recalculate_trig = False
            if pa not in self.psf_centx_notscaled:
                recalculate_trig = True
            else:
                #print(self.psf_centx_notscaled[pa],pa)
                if pa_fk != self.curr_pa_fk[pa] or sep_fk != self.curr_sep_fk[pa]:
                    recalculate_trig = True
            if recalculate_trig: # we could actually store the values for the different pas too...
                self.psf_centx_notscaled[pa] = sep_fk * np.cos(np.radians(90. - pa_fk - pa))
                self.psf_centy_notscaled[pa] = sep_fk * np.sin(np.radians(90. - pa_fk - pa))
                self.curr_pa_fk[pa] = pa_fk
                self.curr_sep_fk[pa] = sep_fk

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

            # create a canvas to place the new PSF in the sector on
            if 0:
                blackboard = np.zeros((ny,nx))
                blackboard.shape = [input_img_shape[0] * input_img_shape[1]]
                blackboard[section_ind] = segment_with_model
                blackboard.shape = [input_img_shape[0],input_img_shape[1]]
                plt.figure(1)
                plt.subplot(1,2,1)
                im = plt.imshow(whiteboard)
                plt.colorbar(im)
                plt.subplot(1,2,2)
                im = plt.imshow(blackboard)
                plt.colorbar(im)
                plt.show()
            whiteboard[(k-row_m):(k+row_p), (l-col_m):(l+col_p)] = 0.0

        return np.array(models)


