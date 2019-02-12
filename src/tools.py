import numpy as np
import os
import re
from random import shuffle
import shutil
import tensorflow as tf
import scipy.io
import scipy.misc
import sklearn.metrics
import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
from mpl_toolkits import mplot3d
import copy
import math
import random
from skimage.measure import block_reduce
import skimage
import threading
import sys

import glob

if sys.version_info >=(2,0):
    print (sys.version)
    import Queue as queue
if sys.version_info >=(3,0):
    print (sys.version)
    import queue

class Data(threading.Thread):
    def __init__(self,config):
        super(Data,self).__init__()
        self.config = config
        self.train_batch_index = 0
        self.test_seq_index = 0

        self.batch_size = config['batch_size']
        self.vox_res_x = config['vox_res_x']
        self.vox_res_y = config['vox_res_y']
        self.categories = config['categories']

        self.queue_train = queue.Queue(3)
        self.stop_queue = False


        self.X_files, self.Y_files = self.load_X_Y_files_paths_all(self.categories)

        self.X_train_files, self.Y_train_files = self.X_files, self.Y_files
        self.X_test_files, self.Y_test_files = [], []
        ''' TODO train test split
        self.X_train_files, self.Y_train_files = self.load_X_Y_files_paths_all( self.train_names,label='train')
        self.X_test_files, self.Y_test_files = self.load_X_Y_files_paths_all(self.test_names, label='test')
        '''

        self.total_train_batch_num = int(len(self.X_train_files) // self.batch_size)
        self.total_test_seq_batch = int(len(self.X_test_files) // self.batch_size)

    @staticmethod
    def plotFromVoxels(voxels,title=''):
        # TODO change to blender render
        if len(voxels.shape)>3:
            x_d = voxels.shape[0]
            y_d = voxels.shape[1]
            z_d = voxels.shape[2]
            v = voxels[:,:,:,0]
            v = np.reshape(v,(x_d,y_d,z_d))
        else:
            v = voxels
        x, y, z = v.nonzero()
        fig = plt.figure()
        ax = fig.add_subplot(111, projection='3d')
        ax.scatter(x, y, z, zdir='z', c='red')
        plt.show()
        plt.title(title)
        show(block=False)

    @staticmethod
    def vox_down_single(vox, to_res):
        from_res = vox.shape[0]
        step = int(from_res / to_res)
        vox = np.reshape(vox,[from_res,from_res,from_res])
        new_vox = block_reduce(vox,(step,step,step),func=np.max)
        new_vox = np.reshape(new_vox,[to_res,to_res,to_res,1])
        return new_vox

    @staticmethod
    def vox_down_batch(vox_bat, to_res):
        from_res = vox_bat.shape[1]
        step = int(from_res / to_res)
        new_vox_bat = []
        for b in range(vox_bat.shape[0]):
            tp = np.reshape(vox_bat[b,:,:,:,:], [from_res,from_res,from_res])
            tp = block_reduce(tp,(step,step,step),func=np.max)
            tp = np.reshape(tp,[to_res,to_res,to_res,1])
            new_vox_bat.append(tp)
        new_vox_bat = np.asarray(new_vox_bat)
        return new_vox_bat

    @staticmethod
    def voxel_grid_padding(a):
        x_d = a.shape[0]
        y_d = a.shape[1]
        z_d = a.shape[2]
        channel = a.shape[3]
        ori_vox_res = 256
        size = [ori_vox_res, ori_vox_res, ori_vox_res,channel]
        b = np.zeros(size,dtype=np.float32)

        bx_s = 0;bx_e = size[0];by_s = 0;by_e = size[1];bz_s = 0; bz_e = size[2]
        ax_s = 0;ax_e = x_d;ay_s = 0;ay_e = y_d;az_s = 0;az_e = z_d
        if x_d > size[0]:
            ax_s = int((x_d - size[0]) / 2)
            ax_e = int((x_d - size[0]) / 2) + size[0]
        else:
            bx_s = int((size[0] - x_d) / 2)
            bx_e = int((size[0] - x_d) / 2) + x_d

        if y_d > size[1]:
            ay_s = int((y_d - size[1]) / 2)
            ay_e = int((y_d - size[1]) / 2) + size[1]
        else:
            by_s = int((size[1] - y_d) / 2)
            by_e = int((size[1] - y_d) / 2) + y_d

        if z_d > size[2]:
            az_s = int((z_d - size[2]) / 2)
            az_e = int((z_d - size[2]) / 2) + size[2]
        else:
            bz_s = int((size[2] - z_d) / 2)
            bz_e = int((size[2] - z_d) / 2) + z_d
        b[bx_s:bx_e, by_s:by_e, bz_s:bz_e,:] = a[ax_s:ax_e, ay_s:ay_e, az_s:az_e, :]

        return b

    @staticmethod
    def load_single_voxel_grid(path, out_vox_res=256):
        with np.load(path) as da:
            voxel_grid = da['arr_0']
        if len(voxel_grid)<=0:
            print (" load_single_voxel_grid error: ", path)
            exit()

        voxel_grid = Data.voxel_grid_padding(voxel_grid)

        ## downsample
        if out_vox_res < 256:
            voxel_grid = Data.vox_down_single(voxel_grid, to_res=out_vox_res)
        return voxel_grid

    @staticmethod
    def single_depth_2_pc(in_depth_path):
        '''Converts a depth image to an array of xyz'''
        depth = skimage.io.imread(in_depth_path)
        depth = np.asarray(depth, dtype=np.float32)

        h = depth.shape[0]
        w = depth.shape[1]

        fov = 49.124/2  # degree
        fx = w/(2.0*np.tan(fov/180.0*np.pi))
        fy = h/(2.0*np.tan(fov/180.0*np.pi))
        k = np.array([[fx, 0, w/2],
                      [0, fy, h/2],
                      [0, 0, 1]], dtype=np.float32)

        xyz_pc = []
        for hi in range(h):
            for wi in range(w):
                if depth[hi, wi]>5 or depth[hi, wi]==0.0:
                    depth[hi, wi] =0.0
                    continue
                x = -(wi - w/2)*depth[hi, wi]/fx
                y = -(hi - h/2)*depth[hi, wi]/fy
                z = depth[hi, wi]
                xyz_pc.append([x, y, z])

        xyz_pc = np.asarray(xyz_pc, dtype=np.float16)

        return xyz_pc

    @staticmethod
    def voxelization(pc_25d, save_path=None, vox_res=256):
        '''Converts an array of xyz to 3d voxel'''

        x_max = max(pc_25d[:, 0]); x_min = min(pc_25d[:, 0])
        y_max = max(pc_25d[:, 1]); y_min = min(pc_25d[:, 1])
        z_max = max(pc_25d[:, 2]); z_min = min(pc_25d[:, 2])
        step = round(max([x_max - x_min, y_max - y_min, z_max - z_min]) / (vox_res - 1), 4)
        x_d_s = int((x_max - x_min) / step)
        y_d_s = int((y_max - y_min) / step)
        z_d_s = int((z_max - z_min) / step)

        vox = np.zeros((x_d_s+1, y_d_s+1, z_d_s+1, 1), dtype=np.int8)
        for k, p in enumerate(pc_25d):

            xd = int((p[0] - x_min) / step)
            yd = int((p[1] - y_min) / step)
            zd = int((p[2] - z_min) / step)
            if xd >= vox_res or yd >= vox_res or zd >= vox_res:
                continue
            if xd > x_d_s or yd > y_d_s or zd > z_d_s:
                continue

            vox[xd, yd, zd, 0] = 1

        if save_path is not None:
            np.savez_compressed(save_path, vox_25d)

        return vox

    @staticmethod
    def depth_to_voxel(in_depth_path, out_vox_res):

        xyz_pc = single_depth_2_pc(in_depth_path)
        vox = voxelization(xyz_pc, vox_res = out_vox_res)
        return vox

    def load_X_Y_files_paths_all(self, categories):
        X_data_files_all = []
        for category in categories:
            if sys.version_info >=(3,0):
                X_data_files_all.extend(glob.glob('./data/processed/{}/**/*depth*.png'.format(category), recursive=True))
            if sys.version_info >=(2,0):
                X_data_files_all.extend(glob.glob('./data/processed/{}/**/*depth*.png'.format(category)))

            Y_data_files_all = []

        return X_data_files_all, Y_data_files_all

    def load_X_Y_voxel_grids(self, X_data_files, Y_data_files):
        '''
        if len(X_data_files) !=self.batch_size or len(Y_data_files)!=self.batch_size:
            print ("load_X_Y_voxel_grids error:", X_data_files, Y_data_files)
            exit()
        '''

        X_voxel_grids = []
        Y_voxel_grids = []
        index = -1
        print(Y_data_files)
        for X_f, Y_f in zip(X_data_files, Y_data_files):
            print('Loading {} and {}...'.format(X_f, Y_f))
            index += 1
            X_voxel_grid = self.depth_to_voxel(X_f, out_vox_res=self.vox_res_x)
            X_voxel_grids.append(X_voxel_grid)

            # TODO process Y as well
            #Y_voxel_grid = self.load_single_voxel_grid(Y_f, out_vox_res=self.vox_res_y)
            #Y_voxel_grids.append(Y_voxel_grid)

        X_voxel_grids = np.asarray(X_voxel_grids)
        Y_voxel_grids = np.asarray(Y_voxel_grids)
        return X_voxel_grids, Y_voxel_grids

    def shuffle_X_Y_files(self):

        temp = list(zip(self.X_train_files, self.Y_train_files))
        random.shuffle(temp)
        self.X_train_files, self.Y_train_files = zip(*temp)


    def load_X_Y_voxel_grids_train_next_batch(self):
        X_data_files = self.X_train_files[self.batch_size * self.train_batch_index:self.batch_size * (self.train_batch_index + 1)]
        Y_data_files = self.Y_train_files[self.batch_size * self.train_batch_index:self.batch_size * (self.train_batch_index + 1)]
        self.train_batch_index += 1

        X_voxel_grids, Y_voxel_grids = self.load_X_Y_voxel_grids(X_data_files, Y_data_files)
        return X_voxel_grids, Y_voxel_grids

    def load_X_Y_voxel_grids_test_next_batch(self,fix_sample=False):
        if fix_sample:
            random.seed(42)
        idx = random.sample(range(len(self.X_test_files)), self.batch_size)
        X_test_files_batch = []
        Y_test_files_batch = []
        for i in idx:
            X_test_files_batch.append(self.X_test_files[i])
            Y_test_files_batch.append(self.Y_test_files[i])

        X_test_batch, Y_test_batch = self.load_X_Y_voxel_grids(X_test_files_batch, Y_test_files_batch)
        return X_test_batch, Y_test_batch

    def run(self):
        while not self.stop_queue:
            ## train
            if not self.queue_train.full():
                if self.train_batch_index>=self.total_train_batch_num:
                    self.shuffle_X_Y_files(label='train')
                    print ('shuffle')
                X_b, Y_b = self.load_X_Y_voxel_grids_train_next_batch()
                self.queue_train.put((X_b, Y_b))

class Ops:

    @staticmethod
    def lrelu(x, leak=0.2):
        f1 = 0.5 * (1 + leak)
        f2 = 0.5 * (1 - leak)
        return f1 * x + f2 * abs(x)

    @staticmethod
    def relu(x):
        return tf.nn.relu(x)

    @staticmethod
    def xxlu(x,label,name=None):
        if label =='relu':
            return  Ops.relu(x)
        if label =='lrelu':
            return  Ops.lrelu(x,leak=0.2)

    @staticmethod
    def variable_sum(var, name):
        with tf.name_scope(name):
            mean = tf.reduce_mean(var)
            tf.summary.scalar('mean', mean)
            stddev = tf.sqrt(tf.reduce_mean(tf.square(var - mean)))
            tf.summary.scalar('stddev', stddev)
            tf.summary.scalar('max', tf.reduce_max(var))
            tf.summary.scalar('min', tf.reduce_min(var))
            tf.summary.histogram('histogram', var)

    @staticmethod
    def variable_count():
        total_para = 0
        for variable in tf.trainable_variables():
            shape = variable.get_shape()
            variable_para = 1
            for dim in shape:
                variable_para *= dim.value
            total_para += variable_para
        return total_para

    @staticmethod
    def fc(x, out_d, name):
        xavier_init = tf.contrib.layers.xavier_initializer()
        zero_init = tf.zeros_initializer()
        in_d = x.get_shape()[1]
        w = tf.get_variable(name + '_w', [in_d, out_d], initializer=xavier_init)
        b = tf.get_variable(name + '_b', [out_d], initializer=zero_init)
        y = tf.nn.bias_add(tf.matmul(x, w), b)
        Ops.variable_sum(w, name)
        return y

    @staticmethod
    def maxpool3d(x,k,s,pad='SAME'):
        ker =[1,k,k,k,1]
        str =[1,s,s,s,1]
        y = tf.nn.max_pool3d(x,ksize=ker,strides=str,padding=pad)
        return y

    @staticmethod
    def conv3d(x, k, out_c, str, name,pad='SAME'):
        xavier_init = tf.contrib.layers.xavier_initializer()
        zero_init = tf.zeros_initializer()
        in_c = x.get_shape()[4]
        w = tf.get_variable(name + '_w', [k, k, k, in_c, out_c], initializer=xavier_init)
        b = tf.get_variable(name + '_b', [out_c], initializer=zero_init)
        stride = [1, str, str, str, 1]
        y = tf.nn.bias_add(tf.nn.conv3d(x, w, stride, pad), b)
        Ops.variable_sum(w, name)
        return y

    @staticmethod
    def deconv3d(x, k, out_c, str, name,pad='SAME'):
        xavier_init = tf.contrib.layers.xavier_initializer()
        zero_init = tf.zeros_initializer()
        [_, in_d1, in_d2, in_d3, in_c] = x.get_shape()
        in_d1 = int(in_d1); in_d2 = int(in_d2); in_d3 = int(in_d3); in_c = int(in_c)
        bat = tf.shape(x)[0]
        w = tf.get_variable(name + '_w', [k, k, k, out_c, in_c], initializer=xavier_init)
        b = tf.get_variable(name + '_b', [out_c], initializer=zero_init)
        out_shape = [bat, in_d1 * str, in_d2 * str, in_d3 * str, out_c]
        stride = [1, str, str, str, 1]
        y = tf.nn.conv3d_transpose(x, w, output_shape=out_shape, strides=stride, padding=pad)
        y = tf.nn.bias_add(y, b)
        Ops.variable_sum(w, name)
        return y

if __name__ == '__main__':
    from config import config
    if sys.version_info>=(2,0):
        print(2)
    if sys.version_info>=(3,0):
        print(3)
    print(config)
    d = Data(config)
    z = d.load_X_Y_voxel_grids_train_next_batch()
    print(z[0].shape, z[1].shape)
    print('hello1')
