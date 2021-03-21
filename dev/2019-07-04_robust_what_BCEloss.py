import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim
from torchvision import datasets, transforms
from torchvision.datasets.mnist import MNIST as MNIST_dataset
from torch.autograd import Variable
import MotionClouds as mc
import os
from display import minmax
from PIL import Image
import datetime

debut = datetime.datetime.now()
date = str(debut)

class MNIST(MNIST_dataset):
    def __getitem__(self, index):
        """
        Args:
            index (int): Index

        Returns:
            tuple: (image, target) where target is index of the target class.
        """
        if self.train:
            img, target = self.train_data[index], self.train_labels[index]
        else:
            img, target = self.test_data[index], self.test_labels[index]

        # doing this so that it is consistent with all other datasets
        # to return a PIL Image
        img = Image.fromarray(img.numpy(), mode='L')

        if self.transform is not None:
            img = self.transform((img, index))

        if self.target_transform is not None:
            target = self.target_transform((target, index))

        return img, target


def MotionCloudNoise(sf_0=0.125, B_sf=3., alpha=.0, N_pic=28, seed=42):
    mc.N_X, mc.N_Y, mc.N_frame = N_pic, N_pic, 1
    fx, fy, ft = mc.get_grids(mc.N_X, mc.N_Y, mc.N_frame)
    env = mc.envelope_gabor(fx, fy, ft, sf_0=sf_0, B_sf=B_sf, B_theta=np.inf, V_X=0., V_Y=0., B_V=0, alpha=alpha)

    z = mc.rectif(mc.random_cloud(env, seed=seed), contrast=1., method='Michelson')
    z = z.reshape((mc.N_X, mc.N_Y))
    return z, env

class WhatShift(object):
    def __init__(self, args, i_offset=None, j_offset=None):
        self.args = args
        if i_offset != None :
            self.i_offset = int(i_offset)
        else : self.i_offset = i_offset
        if j_offset != None :
            self.j_offset = int(j_offset)
        else : self.j_offset = j_offset
        self.args.offset_std = args.what_offset_std
        self.args.offset_max = args.what_offset_max
        
    def __call__(self, sample_index):
        # sample = np.array(sample)

        sample = np.array(sample_index[0])
        index = sample_index[1]

        # print(index)
        np.random.seed(index)

        if self.i_offset is not None:
            i_offset = self.i_offset
            if self.j_offset is None:
                j_offset_f = np.random.randn() * self.args.offset_std
                j_offset_f = minmax(j_offset_f, self.args.offset_max)
                j_offset = int(j_offset_f)
            else:
                j_offset = int(self.j_offset)
        else:
            if self.j_offset is not None:
                j_offset = int(self.j_offset)
                i_offset_f = np.random.randn() * self.args.offset_std
                i_offset_f = minmax(i_offset_f, self.args.offset_max)
                i_offset = int(i_offset_f)
            else:  # self.i_offset is None and self.j_offset is None
                i_offset_f = np.random.randn() * self.args.offset_std
                i_offset_f = minmax(i_offset_f, self.args.offset_max)
                i_offset = int(i_offset_f)
                j_offset_f = np.random.randn() * self.args.offset_std
                j_offset_f = minmax(j_offset_f, self.args.offset_max)
                j_offset = int(j_offset_f)

        N_pic = sample.shape[0]
        data = np.zeros((N_pic, N_pic))
        i_binf_patch = max(0, -i_offset)
        i_bsup_patch = min(N_pic, N_pic -i_offset)
        j_binf_patch = max(0, -j_offset)
        j_bsup_patch = min(N_pic, N_pic -j_offset)
        patch = sample[i_binf_patch:i_bsup_patch, 
                       j_binf_patch:j_bsup_patch]
        
        i_binf_data = max(0, i_offset)
        i_bsup_data = min(N_pic, N_pic + i_offset)
        j_binf_data = max(0, j_offset)
        j_bsup_data = min(N_pic, N_pic + j_offset)
        data[i_binf_data:i_bsup_data,
             j_binf_data:j_bsup_data] = patch
        return data.astype('B')


class WhatBackground(object):
    def __init__(self, contrast=1., noise=1., sf_0=.1, B_sf=.1, seed=0):
        self.contrast = contrast
        self.noise = noise
        self.sf_0 = sf_0
        self.B_sf = B_sf
        self.seed = seed

    def __call__(self, sample):

        # sample from the MNIST dataset
        data = np.array(sample)
        N_pic = data.shape[0]
        if data.min() != data.max():
            data = (data - data.min()) / (data.max() - data.min())
        else:
            data = np.zeros((N_pic, N_pic))
        data *= self.contrast

        seed = self.seed + hash(tuple(data.flatten())) % (2**31 - 1)
        im_noise, env = MotionCloudNoise(sf_0=self.sf_0,
                                         B_sf=self.B_sf,
                                         seed=seed)
        im_noise = 2 * im_noise - 1  # go to [-1, 1] range
        im_noise = self.noise * im_noise
        
        #plt.imshow(im_noise)
        #plt.show()

        im = np.add(data, im_noise)
        im /= 2  # back to [0, 1] range
        im += .5  # back to a .5 baseline
        im = np.clip(im, 0, 1)
        im = im.reshape((28,28,1))
        im *= 255
        return im.astype('B') #Variable(torch.DoubleTensor(im)) #.to(self.device)

class WhatNet(nn.Module):
    def __init__(self, args):
        super(WhatNet, self).__init__()
        self.conv1 = nn.Conv2d(1, 20, 5, 1)
        self.conv2 = nn.Conv2d(20, 50, 5, 1)
        self.fc1 = nn.Linear(4*4*50, 500, bias=False)
        self.fc2 = nn.Linear(500, 10, bias=False)
        self.args = args

    def forward(self, x):
        x = F.relu(self.conv1(x))
        x = F.max_pool2d(x, 2, 2)
        x = F.relu(self.conv2(x))
        x = F.max_pool2d(x, 2, 2)
        x = x.view(-1, 4 * 4 * 50)
        x = F.relu(self.fc1(x))
        if self.args.p_dropout > 0:
            x = F.dropout(x, p=self.args.p_dropout)
        x = self.fc2(x)
        return x #F.log_softmax(x, dim=1)
    
class WhatTrainer:
    def __init__(self, args, model = None, train_loader=None, test_loader=None, device='cpu', seed=0):
        self.args = args
        self.device = device
        self.seed = seed
        torch.manual_seed(seed)
        kwargs = {'num_workers': 1, 'pin_memory': True} if self.device != 'cpu' else {}
        transform=transforms.Compose([
                               WhatShift(args),
                               WhatBackground(contrast=args.contrast, 
                                              noise=args.noise, 
                                              sf_0=args.sf_0, 
                                              B_sf=args.B_sf,
                                              seed=self.seed),
                               transforms.ToTensor(),
                               transforms.Normalize((args.mean,), (args.std,))
                           ])
        if not train_loader:
            dataset_train = MNIST('../data',
                            train=True,
                            download=True,
                            transform=transform,
                            )
            self.train_loader = torch.utils.data.DataLoader(dataset_train,
                                             batch_size=args.minibatch_size,
                                             shuffle=True,
                                             **kwargs)
        else:
            self.train_loader = train_loader

        if not test_loader:
            dataset_test = MNIST('../data',
                            train=False,
                            download=True,
                            transform=transform,
                            )
            self.test_loader = torch.utils.data.DataLoader(dataset_test,
                                             batch_size=args.minibatch_size,
                                             shuffle=True,
                                             **kwargs)
        else:
            self.test_loader = test_loader
            
        if not model:
            self.model = WhatNet(args).to(device)
        else:
            self.model = model
            
        self.loss_func = nn.BCEloss() # nn.CrossEntropyLoss()  # F.nll_loss
        
        if args.do_adam:
            self.optimizer = optim.Adam(self.model.parameters(), lr=args.lr)
        else:
            self.optimizer = optim.SGD(self.model.parameters(), lr=args.lr, momentum=args.momentum)

    def train(self, epoch):
        train(self.args, self.model, self.device, self.train_loader, self.loss_func, self.optimizer, epoch)
        
    def test(self):
        return test(self.args, self.model, self.device, self.test_loader, self.loss_func)

    def posteriorTest(self):
        return posteriorTest(self.args, self.model, self.device, self.test_loader)
    
def train(args, model, device, train_loader, loss_function, optimizer, epoch):
    model.train()
    for batch_idx, (data, target) in enumerate(train_loader):
        data, target = data.to(device), target.to(device)
        optimizer.zero_grad()
        output = model(data)
        loss = loss_function(output, target)
        loss.backward()
        optimizer.step()
        if batch_idx % args.log_interval == 0:
            print('Train Epoch: {}/{} [{}/{} ({:.0f}%)]\tLoss: {:.6f}'.format(
                epoch, args.epochs, batch_idx * len(data), len(train_loader.dataset),
                100. * batch_idx / len(train_loader), loss.item()))

def test(args, model, device, test_loader, loss_function):
    model.eval()
    test_loss = 0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            # test_loss += loss_function(output, target, reduction='sum').item() # sum up batch loss
            test_loss += loss_function(output, target).item()
            pred = output.argmax(dim=1, keepdim=True) # get the index of the max log-probability
            # print(pred)
            # print(pred.size)
            correct += pred.eq(target.view_as(pred)).sum().item()

    test_loss /= len(test_loader.dataset)

    print('\nTest set: Average loss: {:.4f}, Accuracy: {}/{} ({:.0f}%)\n'.format(
        test_loss, correct, len(test_loader.dataset),
        100. * correct / len(test_loader.dataset)))
    return correct / len(test_loader.dataset)

def posteriorTest(args, model, device, test_loader):
    model.eval()
    test_posterior = 0
    correct = 0
    with torch.no_grad():
        for data, target in test_loader:
            data, target = data.to(device), target.to(device)
            output = model(data)
            # posterior = nn.softmax(output)
            posterior = F.softmax(output, dim=1)
            pred = output.argmax(dim=1, keepdim=True) # get the index of the max log-probability
            #!!
            posterior_max = np.zeros(len(pred))
            for i in range(len(pred)):
                posterior_max[i] = posterior[i,pred[i]]
            # posterior_max = posterior[pred]
            # print(posterior_max)
            test_posterior += posterior_max.sum().item()
            correct += pred.eq(target.view_as(pred)).sum().item()

    test_posterior /= len(test_loader.dataset)
    correct /= len(test_loader.dataset)

    print('\nTest set: Max posterior average: {:.4f}, Accuracy: {:.4f}\n'.format(
        test_posterior, correct ))
    return test_posterior, correct

class What:
    def __init__(self, args, train_loader=None, test_loader=None, force=False, seed=0, model=None):
        self.args = args
        self.seed = seed
        self.model = model
        use_cuda = not args.no_cuda and torch.cuda.is_available()
        torch.manual_seed(args.seed)
        device = torch.device("cuda" if use_cuda else "cpu")
        # suffix = f"{self.args.sf_0}_{self.args.B_sf}_{self.args.noise}_{self.args.contrast}"
        suffix = "robust_what_{}_{}_{}_{}_{}epoques_{}_{}h{}".format(self.args.sf_0, self.args.B_sf, self.args.noise, self.args.contrast, self.args.epochs, date[0:10], date[11:13], date[14:16])
        # model_path = f"../data/MNIST_cnn_{suffix}.pt"
        model_path = "../data/MNIST_cnn_{}.pt".format(suffix)
        if os.path.exists(model_path) and not force:
            self.model = torch.load(model_path)
            self.trainer = WhatTrainer(args, 
                                       model=self.model,
                                       train_loader=train_loader, 
                                       test_loader=test_loader, 
                                       device=device,
                                       seed=self.seed)
        else:                                                       
            self.trainer = WhatTrainer(args, model=self.model,
                                       train_loader=train_loader, 
                                       test_loader=test_loader, 
                                       device=device,
                                       seed=self.seed)
            for epoch in range(1, args.epochs + 1):
                self.trainer.train(epoch)
                self.trainer.test()
            self.model = self.trainer.model
            print(model_path)
            if (args.save_model):
                #torch.save(model.state_dict(), "../data/MNIST_cnn.pt")
                torch.save(self.model, model_path)         
    

def main(args=None, train_loader=None, test_loader=None, path="../data/MNIST_cnn.pt"):
    # Training settings
    if args is None:
        import argparse
        parser = argparse.ArgumentParser(description='PyTorch MNIST Example')
        parser.add_argument('--batch-size', type=int, default=64, metavar='N',
                            help='input batch size for training (default: 64)')
        parser.add_argument('--test-batch-size', type=int, default=1000, metavar='N',
                            help='input batch size for testing (default: 1000)')
        parser.add_argument('--epochs', type=int, default=10, metavar='N',
                            help='number of epochs to train (default: 10)')
        parser.add_argument('--lr', type=float, default=0.01, metavar='LR',
                            help='learning rate (default: 0.01)')
        parser.add_argument('--mean', type=float, default=0.1307, metavar='ME',
                            help='learning rate (default: 0.1307)')
        parser.add_argument('--std', type=float, default=0.3081, metavar='ST',
                            help='learning rate (default: 0.3081)')
        parser.add_argument('--momentum', type=float, default=0.5, metavar='M',
                            help='SGD momentum (default: 0.5)')
        parser.add_argument('--no-cuda', action='store_true', default=False,
                            help='disables CUDA training')
        parser.add_argument('--seed', type=int, default=1, metavar='S',
                            help='random seed (default: 1)')
        parser.add_argument('--log-interval', type=int, default=10, metavar='N',
                            help='how many batches to wait before logging training status')
        parser.add_argument('--save-model', action='store_true', default=True,
                            help='For Saving the current Model')

        args = parser.parse_args()
    else:
        args.batch_size = args.minibatch_size
        args.momentum = .5
        args.save_model = True

    what = What(args, train_loader=train_loader, test_loader=test_loader)

if __name__ == '__main__':
    main()
