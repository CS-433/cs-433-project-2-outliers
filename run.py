import numpy as np
import scipy.io as sio 
import torch.nn as nn
import torch 
import matplotlib.pyplot as plt
import os
import argparse

from preprocessing_funcs import get_spikes_with_history, preprocessing, remove_outliers
from model import LSTM
from trainer import train
from quantizer import quantize_network, compute_quantized_weights, quantized_train



#set this to the root directory where you want to save and load data and figures
root = os.path.join('drive')
#set this to the diectory where you want to save data and checkpoints
data_path = os.path.join(root, 'data')
#set this to the diectory where you want to save checkpoints
checkpoint_path = os.path.join(root, 'checkpoints')
#set this to directory where you want to save figures
figure_path = os.path.join(root, 'figures')


parser = argparse.ArgumentParser()
parser.add_argument("--pre_trained", default=False, help="Set to True if you want to use pre-trained model", type=bool)
parser.add_argument("--fixed_pt_quantization", default=False, help="Set to True if you want to use fixed point quantization", type=bool)
parser.add_argument("--pruning", default=False, help="Set to True if you want to use pruning", type=bool)
parser.add_argument("--trained_quantization", default=False, help="Set to True if you want to use trained quantization", type=bool)

args = parser.parse_args()
pre_trained = args.pre_trained
fixed_pt_quantize = args.fixed_pt_quantization
pruning = args.pruning
trained_quantization = args.trained_quantization


for Idx_subject in list([10]): # 3 subjects index 10-12

       
        for Finger in list([0]): # 5 fingers for each subject. 0:thumb, 1:index, 2:middle ...
            
            #load training data (TrainX: feature vectors, TrainY: labels)
            matData = sio.loadmat(data_path + '/BCImoreData_Subj_'+str(Idx_subject)+'_200msLMP.mat')
            TrainX = matData['Data_Feature'].transpose()
            TrainY = matData['SmoothedFinger']
            TrainY = TrainY [:,Finger]
            TrainY = TrainY.reshape(TrainY.shape[0],1)
            #load testing data (TestX: feature vectors, TestY: labels)
            matData = sio.loadmat(data_path + '/BCImoreData_Subj_'+str(Idx_subject)+'_200msLMPTest.mat')
            TestX = matData['Data_Feature'].transpose()
            TestY = matData['SmoothedFinger']
            TestY = TestY[:,Finger]
            TestY = TestY.reshape(TestY.shape[0],1)
            
            # preprocessing 
            TrainX = remove_outliers(TrainX)
            
            x_scaler, y_scaler, TrainX, TestX, TrainY, TestY  = preprocessing(TrainX,TestX,TrainY,TestY)
            
            
            # from here, we reconstruct the input by "looking back" a few steps
            bins_before= 20 #How many bins of neural data prior to the output are used for decoding
            bins_current=1 #Whether to use concurrent time bin of neural data
            bins_after=0 #How many bins of neural data after the output are used for decoding
            
            TrainX=get_spikes_with_history(TrainX,bins_before,bins_after,bins_current)
            TrainX, TrainY = TrainX[bins_before:,:,:], TrainY[bins_before:,]
         
            TestX=get_spikes_with_history(TestX,bins_before,bins_after,bins_current)
            TestX, TestY = TestX[bins_before:,:,:], TestY[bins_before:,]
            
            # Now, we reconstructed TrainX/TestX to have a shape (num_of_samples, sequence_length, input_size)
            # We can fit this to the LSTM
            
            print("Run for subject " + str(Idx_subject) + " finger "+str(Finger))

            n_hidden = 20
            n_layers = 5
            input_dim = TrainX.shape[2]
            output_dim = TrainY.shape[1]
            seq_len =  TrainX.shape[1]

            net = LSTM(input_dim, output_dim, seq_len,  n_hidden, n_layers, fixed_pt_quantize = fixed_pt_quantize)

            lossfunc = nn.MSELoss()

            lr = 0.002
            if fixed_pt_quantize:
              lr = 0.003

            optimizer = torch.optim.Adamax(net.parameters(), lr=lr)


            ##############################################PRUNING###########################################################################
            if pruning:
                print("Pruning============================================================================")
                figure_name = "/Subject_" + str(Idx_subject) + "_Finger_"+str(Finger)+"_pruning"

                PATH_pre_trained = checkpoint_path + '/s'+ str(Idx_subject) + '_f'+str(Finger)+'_trained_model'
                net.load_state_dict(torch.load(PATH_pre_trained))
                net.train()
                net.threshold_pruning()
                #train the prunned model:
                try:
                    corr_train, corr_val, corr_test = train(TrainX, TrainY, TestX, TestY, net, lossfunc, optimizer, num_epoch=10, clip = 5, Finger = Finger)
                except KeyboardInterrupt:
                    #save the model
                    print("saving...")
                

                net.eval()
                pred,h = net(torch.from_numpy(TestX).float(), net.init_hidden(TestX.shape[0]))
                

            ##############################################TRAINED QUANTIZATION##############################################################
            elif trained_quantization:
                print("Trained Quantization===================================================================")
                figure_name = "/Subject_" + str(Idx_subject) + "_Finger_"+str(Finger)+"_trained_quant"
               
                PATH_pre_trained = checkpoint_path + '/s'+ str(Idx_subject) + '_f'+str(Finger)+'_trained_model'
                net.load_state_dict(torch.load(PATH_pre_trained))
                k=8
                #initialize the quantiezed weights using the weights from the trained netwrok:
                net = compute_quantized_weights(net,k)
                net.train()
                
                #train the quantized netwok
                quantized_corr_train, quantized_corr_val, quantized_corr_test = quantized_train(TrainX, TrainY,TestX,TestY, net, lossfunc, optimizer, num_epoch = 60, clip = 5)
                #set the model's parameters to their quantized version
                net = quantize_network(net)
               
                
                net.eval()
                pred,h = net(torch.from_numpy(TestX).float(), net.init_hidden(TestX.shape[0]), quant=True)
            
            #############################################BASELINE###########################################################################
            else:
                print("Baseline ===================================================================")
                ##training the initial model
                if fixed_pt_quantize:
                    figure_name = "/Subject_" + str(Idx_subject) + "_Finger_"+str(Finger)+"_fp_quant"
                    PATH_pre_trained = checkpoint_path + '/Sbj' + str(Idx_subject) + 'f'+str(Finger)+'_trained_model_fixed_pt_quantization'+str(fixed_pt_quantize)
                else:
                    figure_name = "/Subject_" + str(Idx_subject) + "_Finger_"+str(Finger)+"_baseline"
                    PATH_pre_trained = checkpoint_path + '/s'+ str(Idx_subject) + '_f'+str(Finger)+'_trained_model'
                
                if pre_trained and fixed_pt_quantize:
                    net = torch.load(PATH_pre_trained)
                elif pre_trained:
                    net.load_state_dict(torch.load(PATH_pre_trained))

                else:
                    net.train()
                    try:
                        corr_train, corr_val, corr_test = train(TrainX, TrainY,TestX,TestY, net, lossfunc, optimizer, num_epoch = 200, clip = 5, Finger=Finger)
                    except KeyboardInterrupt:
                        #save the model
                        print("saving...")
                    
                    torch.save(net.state_dict(), PATH_pre_trained)
                    print("model saved")

                ##test baseline model
                net.eval()
                pred,h = net(torch.from_numpy(TestX).float(), net.init_hidden(TestX.shape[0]))

               

            
            pred = pred.detach().numpy()[-1,:,:]
            pred = y_scaler.inverse_transform(pred)
            TestY = y_scaler.inverse_transform(TestY)
            pred = pred.reshape((-1,))
            corrcoef = np.corrcoef(pred,TestY.reshape((-1,)))

            TestYShifted = TestY
            x = np.arange(TestYShifted.shape[0])
            
            fig_label = plt.figure(figsize=(15,10))
            plt.title("Subject_" + str(Idx_subject) + "_Finger_"+str(Finger))
            plt.plot(x, TestYShifted)
            plt.plot(x, pred)
            fig_label.savefig(figure_path + figure_name)

            
            print ('Correlation coefficient test : {corrcoef}'.format(corrcoef=corrcoef[0,1]))   
