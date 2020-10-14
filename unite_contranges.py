#Allison Towner
#09 October 2020

#continuum_selections.py in analysis code is located at:
#in ALMA_IMF/reduction/analysis/

import numpy as np
import sys
sys.path.append('.')
from parse_contdotdat import parse_contdotdat

#Read in metadata from .json file
basepath = '/orange/adamginsburg/ALMA_IMF/2017.1.01355.L'
with open(basepath + '/contdatfiles.json', 'r') as fh:
    contdatfiles = json.load(fh)
with open(basepath + '/metadata.json', 'r') as fh:
    metadata = json.load(fh)


#Set field and band name - this should be detected automatically in the final version of the script but is hardwired here for testing purposes
field = 'G327.29'
band = 'B3'

#use parse_contdotdat to read the 12m-long, 12m-short, and 7m contranges into arrays from their cont.dat files
#NOTE: This part of the script assumes there are only three cont.dat files, and they are in a specific order!
#This should be the same across all metadata but if it is not this part of the script will need to be altered.
contdotdat_ranges = []
for i,m in enumerate(metadata[band][field]['cont.dat']):
    m = str(m)
    contdotdat_ranges.append(parse_contdotdat(metadata[band][field]['cont.dat'][m]))

#Open the files to which we will write the final, merged contranges, and write field name at the top
f_12m = open(field+'.'+band+'.12m.cont.dat','w')
f_7m = open(field+'.'+band+'.7m.cont.dat','w')
f_12m.write('Field: %s\n\n' %(field))
f_7m.write('Field: %s\n\n' %(field))

#Keep this! This dictionary tells us how many channels are in each spw. If the metadata files are ever altered to include nchans for each spw, this could be removed, but for now it must remain in order to create the freq arrays
numchans = {
    'B3': {'16': 2048,
           '18': 2048,
           '20': 2048,
           '22': 2048,
           #
           '25': 1920,
           '27': 1920,
           '29': 1920,
           '31': 1920
        },
    'B6': {'16': 2048,
           '18': 1024,
           '20': 512,
           '22': 2048,
           '24': 1024,
           '26': 512,
           '28': 2048,
           '30': 2048,
           #
           '25': 1920,
           '27': 960,
           '29': 480,
           '31': 1920,
           '33': 960,
           '35': 480,
           '37': 1920,
           '39': 1920
        }
}


numspw = len(metadata[band][field]['spws'][0]) #Determine how many spws we are working with (assumes the same number across the 12ml, 12ms, and 7m configurations)

for i in range(0,numspw):#for however many spws

    #Initialize fmin and fmax
    fmin = 1E14 #in Hz
    fmax = 1E0 #in Hz
    
    #initialize spw_all
    spw_all = np.array([]) 
    for j in range(0,len(metadata[band][field]['spws'])): #for however many configs

        spw_all = np.append(metadata[band][field]['spws'][j][i],spw_all) #we will need this later

        #Set fmin and fmax based on the global min and max frequencies for a given spw across all array configs
        if metadata[band][field]['freqs'][j][i][0] < fmin:
            fmin = metadata[band][field]['freqs'][j][i][0]
        if metadata[band][field]['freqs'][j][i][1] > fmax:
            fmax = metadata[band][field]['freqs'][j][i][1]

    
    #Set up arrays over which we will iterate to determine combined contranges
    spw = str(metadata[band][field]['spws'][0][i]) #find what spw we are using
    if np.remainder(int(spw),2) == 1: #if we are using a 12m spw, switch to using a 7m spw (more channels)
        spw_forchans = str(int(spw)-9)
    nchans = numchans[band][spw_forchans]
    chanwidth = (fmax - fmin)/(3.*nchans)
    extrachans = 20
    contfreqs = np.zeros([len(np.arange(fmin-extrachans*chanwidth,fmax+extrachans*chanwidth,chanwidth))])

    #Get the 7m name and the 12m name for the spw we are currently working with, write it out to the respective outfiles
    spw_7m = str(int(np.min(spw_all)))
    spw_12m = str(int(np.max(spw_all)))
    f_12m.write('SpectralWindow: %s\n' %(spw_12m))
    f_7m.write('SpectralWindow: %s\n' %(spw_7m))

    #for each of the contranges (from the three contrange.dat files)
    for contrange in contdotdat_ranges:

        pairs = contrange.split(';') #split the contrange list into pairs

        for p,pair in enumerate(pairs):#for each pair
            minimum = float(pair.split('~')[0])*1E9 #convert GHz to Hz
            maximum = float(pair.split('~')[1][:-3])*1E9 #convert GHz to Hz

            #for each pair, iterate over our full frequency range;
            #if a frequency falls within the range of a given pair, change contfreqs[f] from 0 to 1
            for f,freq in enumerate(np.arange(fmin-extrachans*chanwidth,fmax+extrachans*chanwidth,chanwidth)):
                if freq > minimum and freq < (maximum+chanwidth):
                    contfreqs[f] = 1.0

    #Now iterate over our full frequency range again
    for f,freq in enumerate(np.arange(fmin-extrachans*chanwidth,fmax+extrachans*chanwidth,chanwidth)):
        freqlength = len(np.arange(fmin-extrachans*chanwidth,fmax+extrachans*chanwidth,chanwidth))

        if f > 0:#we have to start at f==1 for indexing reasons or python will yell at us

            #if contfreqs changes from 0 to 1, write the first part of the contrange
            if contfreqs[f] == 1 and contfreqs[f-1] == 0:
                f_12m.write('%f~' %(freq/1E9)) #convert Hz to GHz and write out
                f_7m.write('%f~' %(freq/1E9)) #convert Hz to GHz and write out

            #if contfreqs changes from 1 to 0 OR contfreqs[f]==1 and you are at the end of the list,
            #write the second part of the contrange and start a new line
            if (contfreqs[f] == 0 and contfreqs[f-1] == 1) or (contfreqs[f] == 1 and f == (freqlength-1)):
                f_12m.write('%fGHz LSRK\n' %((freq-chanwidth)/1E9)) #convert Hz to GHz and write out
                f_7m.write('%fGHz LSRK\n' %((freq-chanwidth)/1E9)) #convert Hz to GHz and write out

    #Write a new line for extra spacing between spws in the text files
    f_12m.write('\n')
    f_7m.write('\n')

#Once you have finished iterating over all spws, close the output files
f_12m.close()
f_7m.close()
