"""
Line imaging script.  There needs to be a to_image.json file in the directory
this is run in.  The to_image.json file is produced by the split_windows.py
script.

You can set the following environmental variables for this script:
    CHANCHUNKS=<number>
        The chanchunks parameter for tclean.  Depending on the version, it may
        be acceptable to specify this as -1, or it has to be positive.  This is
        the number of channels that will be imaged all at once; if this is too
        large, the data won't fit into memory and CASA will crash.
    EXCLUDE_7M=<boolean>
        If this parameter is set (to anything), the 7m data will not be
        included in the images if they are present.
    FIELD_ID=<name>
        If this parameter is set, filter out the imaging targets and only image
        fields with this name (e.g., "W43-MM1", "W51-E", etc.)
    BAND_NUMBERS=<band(s)>
        Image this/these bands.  Can be "3", "6", or "3,6" (no quotes)
    LINE_NAME=<name>
        Image only one line at each run.  Can be 'n2hp', 'CO' (Case insensitive)
"""

import json
import os
import numpy as np
import astropy.units as u
from astropy import constants
try:
    from tasks import tclean, uvcontsub, impbcor
except ImportError:
    # futureproofing: CASA 6 imports this way
    from casatasks import tclean, uvcontsub, impbcor
from parse_contdotdat import parse_contdotdat, freq_selection_overlap
from metadata_tools import determine_imsizes, determine_phasecenter, is_7m, logprint
from imaging_parameters import line_imaging_parameters, selfcal_pars, line_parameters
from taskinit import msmdtool, iatool, mstool
from metadata_tools import effectiveResolutionAtFreq
msmd = msmdtool()
ia = iatool()
ms = mstool()

with open('to_image.json', 'r') as fh:
    to_image = json.load(fh)


if os.getenv('FIELD_ID'):
    field_id = os.getenv('FIELD_ID')
    for band in to_image:
        to_image[band] = {key:value for key, value in to_image[band].items()
                          if key == field_id}


if os.getenv('BAND_NUMBERS'):
    band_list = list(map(lambda x: "B"+x, os.getenv('BAND_NUMBERS').split(',')))
    for BB in band_list:
        if BB not in to_image:
            raise ValueError("Band {0} was specified but is not in to_image.json"
                             .format(BB))
else:
    band_list = list(to_image.keys())

imaging_root = "imaging_results"
if not os.path.exists(imaging_root):
    os.mkdir(imaging_root)

if 'exclude_7m' not in locals():
    if os.getenv('EXCLUDE_7M') is not None:
        exclude_7m = bool(os.getenv('EXCLUDE_7M').lower() == 'true')
    else:
        exclude_7m = False

if os.getenv('LINE_NAME'):
    line_name = os.getenv('LINE_NAME').lower()
else:
    raise ValueError("line_name was not defined")

# set the 'chanchunks' parameter globally.
# CASAguides recommend chanchunks=-1, but this resulted in: 2018-09-05 23:16:34     SEVERE  tclean::task_tclean::   Exception from task_tclean : Invalid Gridding/FTM Parameter set : Must have at least 1 chanchunk
chanchunks = os.getenv('CHANCHUNKS') or 16

# global default: only do robust 0 for lines
robust = 0

for band in band_list:
    for field in to_image[band]:
        for spw in to_image[band][field]:

            # python 2.7 specific hack: force 'field' to be a bytestring
            # instead of a unicode string (CASA's lower-level functions
            # can't accept unicode strings)
            field = str(field)
            spw = str(spw)
            band = str(band)

            vis = list(map(str, to_image[band][field][spw]))

            # load in the line parameter info
            linpars = line_parameters[field][line_name]
            restfreq = u.Quantity(linpars['restfreq'])
            vlsr = u.Quantity(linpars['vlsr'])

            # check that the line is in range
            ms.open(vis[0])
            # assume spw is 0 because we're working on split data
            freqs = ms.cvelfreqs(spwids=0, outframe='LSRK') * u.Hz
            targetfreq = restfreq * (1 - vlsr/constants.c)
            if freqs.min() > targetfreq or freqs.max() < targetfreq:
                # Skip this spw: it is not in range
                logprint("Skipped spectral window {0} for line {1} because it's out of range"
                         .format(spw, line_name),
                         origin='almaimf_line_imaging')
                continue
            else:
                logprint("Matched spectral window {0} to line {1}"
                         .format(spw, line_name),
                         origin='almaimf_line_imaging')


            if exclude_7m:
                # don't use variable name 'ms' in python2.7!
                vis = [ms_ for ms_ in vis if not is_7m(ms_)]
                arrayname = '12M'
            else:
                arrayname = '7M12M'

            lineimagename = os.path.join(imaging_root,
                                         "{0}_{1}_spw{2}_{3}_{4}".format(field,
                                                                         band,
                                                                         spw,
                                                                         arrayname,
                                                                         line_name))


            logprint("Measurement sets are: " + str(vis),
                     origin='almaimf_line_imaging')
            coosys, racen, deccen = determine_phasecenter(ms=vis, field=field)
            phasecenter = "{0} {1}deg {2}deg".format(coosys, racen, deccen)
            (dra, ddec, pixscale) = list(determine_imsizes(mses=vis, field=field,
                                                           phasecenter=(racen, deccen),
                                                           spw=0, pixfraction_of_fwhm=1/3.,
                                                           exclude_7m=exclude_7m,
                                                           min_pixscale=0.1, # arcsec
                                                          ))
            imsize = [int(dra), int(ddec)]
            cellsize = ['{0:0.2f}arcsec'.format(pixscale)] * 2

            dirty_tclean_made_residual = False


            # prepare for the imaging parameters
            pars_key = "{0}_{1}_{2}_robust{3}".format(field, band, arrayname, robust)
            impars = line_imaging_parameters[pars_key]

            # calculate the channel width
            chanwidths = []
            for vv in vis:
                msmd.open(vv)
                count_spws = len(msmd.spwsforfield(field))
                msmd.close()
                chanwidth = np.max([np.abs(
                    effectiveResolutionAtFreq(vv,
                                              spw='{0}'.format(i),
                                              freq=u.Quantity(linpars['restfreq']).to(u.GHz),
                                              kms=True)) for i in
                    range(count_spws)])
                chanwidths.append(chanwidth)
            # chanwidth: mean? max?
            chanwidth = np.mean(chanwidths)
            logprint("Channel widths were {0}, mean = {1}".format(chanwidths,
                                                                  chanwidth),
                     origin="almaimf_line_imaging")
            if np.any(np.array(chanwidths) - chanwidth > 1e-4):
                raise ValueError("Varying channel widths.")
            local_impars = {}
            local_impars['width'] = '{0:.2f}km/s'.format(chanwidth)
            local_impars['restfreq'] = linpars['restfreq']
            # calculate vstart
            vstart = u.Quantity(linpars['vlsr'])-u.Quantity(linpars['cubewidth'])/2
            local_impars['start'] = '{0:.1f}km/s'.format(vstart.value)
            local_impars['imsize'] = imsize
            local_impars['cell'] = cellsize
            local_impars['phasecenter'] = phasecenter
            local_impars['field'] = [field.encode()]*len(vis)
            local_impars['chanchunks'] = chanchunks

            local_impars['nchan'] = int((u.Quantity(line_parameters[field][line_name]['cubewidth'])
                                   / u.Quantity(local_impars['width'])).value)
            if local_impars['nchan'] < local_impars['chanchunks']:
                local_impars['chanchunks'] = local_impars['nchan']
            impars.update(local_impars)


            # start with cube imaging

            if not os.path.exists(lineimagename+".image") and not os.path.exists(lineimagename+".residual"):
                if os.path.exists(lineimagename+".psf"):
                    logprint("WARNING: The PSF for {0} exists, but no image exists."
                             "  This likely implies that an ongoing or incomplete "
                             "imaging run for this file exists.  It will not be "
                             "imaged this time; please check what is happening.  "
                             "(this warning issued /before/ dirty imaging)"
                             .format(lineimagename),
                             origin='almaimf_line_imaging')
                    continue
                # first iteration makes a dirty image to estimate the RMS
                impars_dirty = impars.copy()
                impars_dirty['niter'] = 0

                logprint("Dirty imaging parameters are {0}".format(impars_dirty),
                         origin='almaimf_line_imaging')
                tclean(vis=vis,
                       imagename=lineimagename,
                       restoringbeam='', # do not use restoringbeam='common'
                       # it results in bad edge channels dominating the beam
                       **impars_dirty
                      )
                if os.path.exists(lineimagename+".image"):
                    # tclean with niter=0 is not supposed to produce a .image file,
                    # but if it does (and it appears to have done so on at
                    # least one run), we still want to clean the cube
                    dirty_tclean_made_residual = True
            elif not os.path.exists(lineimagename+".residual"):
                raise ValueError("The residual image is required for further imaging.")

            if os.path.exists(lineimagename+".psf") and not os.path.exists(lineimagename+".image"):
                logprint("WARNING: The PSF for {0} exists, but no image exists."
                         "  This likely implies that an ongoing or incomplete "
                         "imaging run for this file exists.  It will not be "
                         "imaged this time; please check what is happening."
                         "(warning issued /after/ dirty imaging)"
                         .format(lineimagename),
                         origin='almaimf_line_imaging')
                # just skip the rest here - that means no contsub imaging
                continue

            # the threshold needs to be computed if any imaging is to be done (either contsub or not)
            # no .image file is produced, only a residual
            logprint("Computing residual image statistics for {0}".format(lineimagename), origin='almaimf_line_imaging')
            ia.open(lineimagename+".residual")
            stats = ia.statistics(robust=True)
            rms = float(stats['medabsdevmed'] * 1.482602218505602)
            threshold = "{0:0.4f}Jy".format(5*rms) # 3 rms might be OK in practice
            logprint("Threshold used = {0} = 5x{1}".format(threshold, rms),
                     origin='almaimf_line_imaging')
            ia.close()


            if dirty_tclean_made_residual or not os.path.exists(lineimagename+".image"):
                # continue imaging using a threshold
                local_impars['threshold'] = threshold

                impars.update(local_impars)

                logprint("Imaging parameters are {0}".format(impars),
                         origin='almaimf_line_imaging')
                tclean(vis=vis,
                       imagename=lineimagename,
                       restoringbeam='', # do not use restoringbeam='common'
                       # it results in bad edge channels dominating the beam
                       **impars
                      )
                impbcor(imagename=lineimagename+'.image',
                        pbimage=lineimagename+'.pb',
                        outfile=lineimagename+'.image.pbcor', overwrite=True)


            # TODO: Save the desired files, maybe as FITS or maybe not?


            # the cont_channel_selection is purely in frequency, so it should
            # "just work"
            # (there may be several cont.dats - we're just grabbing the first)
            # Different data sets are actually found to have different channel selections.
            path = os.path.split(vis[0])[0]

            contfile = os.path.join(path, '../calibration/cont.dat')

            cont_freq_selection = parse_contdotdat(contfile)
            logprint("Selected {0} as continuum channels".format(cont_freq_selection), origin='almaimf_line_imaging')

            for vv in vis:
                if not os.path.exists(vv+".contsub"):
                    new_freq_selection = freq_selection_overlap(vv,
                                                                cont_freq_selection)
                    uvcontsub(vis=vv,
                              fitspw=new_freq_selection,
                              excludechans=False, # fit the regions in fitspw
                              combine='spw', # redundant since we're working on single spw's
                              solint='int',
                              fitorder=1,
                              want_cont=False)

            if os.path.exists(lineimagename+".contsub.psf") and not os.path.exists(lineimagename+".contsub.image"):
                logprint("WARNING: The PSF for {0} contsub exists, "
                         "but no image exists."
                         "  This likely implies that an ongoing or incomplete "
                         "imaging run for this file exists.  It will not be "
                         "imaged this time; please check what is happening.  "
                         "(warning issued after imaging, before contsub imaging)"
                         .format(lineimagename),
                         origin='almaimf_line_imaging')
            elif not os.path.exists(lineimagename+".contsub.image"):

                pars_key = "{0}_{1}_{2}_robust{3}_contsub".format(field, band, arrayname, robust)
                impars = line_imaging_parameters[pars_key]
                impars.update(local_impars)
                # Todo: should we re-calculate the threshold after the continuum subtraction?
                tclean(vis=[vv+".contsub" for vv in vis],
                       imagename=lineimagename+".contsub",
                       restoringbeam='',
                       **impars
                      )
                impbcor(imagename=lineimagename+'.image',
                        pbimage=lineimagename+'.pb',
                        outfile=lineimagename+'.image.pbcor', overwrite=True)

            logprint("Completed {0}".format(vis), origin='almaimf_line_imaging')
