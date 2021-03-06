"""
Baseline for CIL project on road segmentation.
This simple baseline consits of a CNN with two convolutional+pooling layers with a soft-max loss
"""

import gzip
import os
import sys
import urllib
import matplotlib.image as mpimg
from PIL import Image

import csv
import time
import code
import tensorflow.python.platform
import numpy as np
import tensorflow as tf
import math
import scipy
import scipy.signal

NUM_CHANNELS = 3 # RGB images
PIXEL_DEPTH = 255
NUM_LABELS = 2
TRAINING_SIZE = 100
SEED = 201
NP_SEED = int(time.time());
BATCH_SIZE = 64 # 64
BALANCE_SIZE_OF_CLASSES = True

RESTORE_MODEL = True # If True, restore existing model instead of training a new one
TERMINATE_AFTER_TIME = True
NUM_EPOCHS = 1
MAX_TRAINING_TIME_IN_SEC = 2 * 28800
RECORDING_STEP = 1000

# Set image patch size
# IMG_PATCH_SIZE should be a multiple of 4
# image size should be an integer multiple of this number!
IMG_PATCHES_RESTORE = True
IMG_WIDTH = 400;
IMG_HEIGHT = 400;
IMG_PATCH_SIZE = 16
IMG_PATCH_STRIDE = 8

###### POST TRAINING SETTINGS ######
VALIDATION_SIZE = 20000  # Size of the validation set.
VALIDATE = True;
VISUALIZE_PREDICTION_ON_TRAINING_SET = True
VISUALIZE_NUM = -1
RUN_ON_TEST_SET = True
TEST_SIZE = 50

tf.app.flags.DEFINE_string('train_dir', 'tmp/',
                           """Directory where to write event logs """
                           """and checkpoint.""")
FLAGS = tf.app.flags.FLAGS

def subtract_mean(img):
    gray_img = 0.2989*img[:,:,0] + 0.5870*img[:,:,1] + 0.1140*img[:,:,2]
    img -= np.matrix(gray_img).mean()

def prediction_to_mask(labels, width, height):
    mask = np.zeros([height, width])
    idx = 0
    for i in range(0,height):
        for j in range(0,width):
            mask[i][j] = 0 if labels[idx][0] > 0.5 else 1
            idx = idx + 1
    return mask

def mask_to_prediction(mask):
    (height, width) = mask.shape;
    prediction = np.zeros([height * width, 2])
    idx = 0
    for i in range(0,height):
        for j in range(0,width):
            if mask[i][j] == 1:
                prediction[idx][1] = 1
            else:
                prediction[idx][0] = 1
            idx = idx + 1
    return prediction

def augment_image(img, out_ls, num_of_transformations):
    out_ls.append(img)
    if num_of_transformations > 0:
        out_ls.append(np.fliplr(img))
    if num_of_transformations > 1:
        out_ls.append(np.flipud(img))
    if num_of_transformations > 2:
        out_ls.append(np.rot90(img))
    if num_of_transformations > 3:
        out_ls.append(np.rot90(np.rot90(img)))

# Extract patches from a given image
def img_crop(im, patch_size, stride, num_of_transformations):
    list_patches = []
    imgwidth = im.shape[0]
    imgheight = im.shape[1]
    is_2d = len(im.shape) < 3

    for i in range(0,imgheight - patch_size + 1, stride):
        for j in range(0,imgwidth - patch_size + 1, stride):
            if is_2d:
                im_patch = [im[j:j+patch_size, i:i+patch_size]]
            else:
                im_patch = im[j:j+patch_size, i:i+patch_size, :]
                subtract_mean(im_patch)
            augment_image(im_patch, list_patches, num_of_transformations)
    return list_patches

def extract_data(filename, num_images, patch_size = IMG_PATCH_SIZE, patch_stride = IMG_PATCH_STRIDE, num_of_transformations = 4):
    """Extract the images into a 4D tensor [image index, y, x, channels].
    Values are rescaled from [0, 255] down to [-0.5, 0.5].
    """
    imgs = []
    for i in range(1, num_images+1):
        imageid = "satImage_%.3d" % i
        image_filename = filename + imageid + ".png"
        if os.path.isfile(image_filename):
            print ('Loading ' + image_filename)
            img = mpimg.imread(image_filename)
            imgs.append(img)
        else:
            print ('File ' + image_filename + ' does not exist')

    num_images = len(imgs)
    IMG_WIDTH = imgs[0].shape[0]
    IMG_HEIGHT = imgs[0].shape[1]
    N_PATCHES_PER_IMAGE = (IMG_WIDTH/patch_size)*(IMG_HEIGHT/patch_size)
    print('Extracting patches...')
    img_patches = [img_crop(imgs[i], patch_size, patch_stride, num_of_transformations) for i in range(num_images)]
    data = [img_patches[i][j] for i in range(len(img_patches)) for j in range(len(img_patches[i]))]
    print(str(len(data)) + ' patches extracted.')

    return np.asarray(data)
        
# Assign a label to a patch v
def value_to_class(v):
    foreground_threshold = 0.25 # percentage of pixels > 1 required to assign a foreground label to a patch
    df = np.sum(v)
    if df > foreground_threshold:
        # Road
        return [0, 1]
    else:
        # Non-road
        return [1, 0]

# Extract label images
def extract_labels(filename, num_images, patch_size = IMG_PATCH_SIZE, patch_stride = IMG_PATCH_STRIDE, num_of_transformations = 4):
    """Extract the labels into a 1-hot matrix [image index, label index]."""
    gt_imgs = []
    for i in range(1, num_images+1):
        imageid = "satImage_%.3d" % i
        image_filename = filename + imageid + ".png"
        if os.path.isfile(image_filename):
            print ('Loading ' + image_filename)
            img = mpimg.imread(image_filename)
            gt_imgs.append(img)
        else:
            print ('File ' + image_filename + ' does not exist')

    num_images = len(gt_imgs)
    print('Extracting patches...')
    gt_patches = [img_crop(gt_imgs[i], patch_size, patch_stride, num_of_transformations) for i in range(num_images)]
    data = np.asarray([gt_patches[i][j] for i in range(len(gt_patches)) for j in range(len(gt_patches[i]))])
    labels = np.asarray([value_to_class(np.mean(data[i])) for i in range(len(data))])
    print(str(len(data)) + ' patches extracted.')

    # Convert to dense 1-hot representation.
    return labels.astype(np.float32)

def error_rate(predictions, labels):
    return 100.0 - (100.0 * np.sum(np.argmax(predictions, 1) == np.argmax(labels, 1)) / predictions.shape[0])

# Convert array of labels to an image
def label_to_img(imgwidth, imgheight, w, h, labels):
    array_labels = np.zeros([imgwidth, imgheight])
    idx = 0
    for i in range(0,imgheight,h):
        for j in range(0,imgwidth,w):
            if labels[idx][0] > 0.5:
                l = 0
            else:
                l = 1
            array_labels[j:j+w, i:i+h] = l
            idx = idx + 1
    return array_labels

def img_float_to_uint8(img):
    rimg = img - np.min(img)
    rimg = (rimg / np.max(rimg) * PIXEL_DEPTH).round().astype(np.uint8)
    return rimg

def concatenate_images(img, gt_img):
    nChannels = len(gt_img.shape)
    w = gt_img.shape[0]
    h = gt_img.shape[1]
    if nChannels == 3:
        cimg = np.concatenate((img, gt_img), axis=1)
    else:
        gt_img_3c = np.zeros((w, h, 3), dtype=np.uint8)
        gt_img8 = img_float_to_uint8(gt_img)          
        gt_img_3c[:,:,0] = gt_img8
        gt_img_3c[:,:,1] = gt_img8
        gt_img_3c[:,:,2] = gt_img8
        img8 = img_float_to_uint8(img)
        cimg = np.concatenate((img8, gt_img_3c), axis=1)
    return cimg

def make_img_overlay(img, predicted_img, true_img = None):
    w = img.shape[0]
    h = img.shape[1]
    color_mask = np.zeros((w, h, 3), dtype=np.uint8)
    color_mask[:,:,0] = predicted_img * PIXEL_DEPTH
    if (true_img != None):
        color_mask[:,:,1] = true_img * PIXEL_DEPTH

    img8 = img_float_to_uint8(img)
    background = Image.fromarray(img8, 'RGB').convert("RGBA")
    overlay = Image.fromarray(color_mask, 'RGB').convert("RGBA")
    new_img = Image.blend(background, overlay, 0.2)
    return new_img

def main(argv=None):  # pylint: disable=unused-argument
    np.random.seed(NP_SEED)
    train_data_filename = 'data/training/images/'
    train_labels_filename = 'data/training/groundtruth/'
    test_data_filename = 'data/test_set/'

    # Extract it into np arrays.
    if IMG_PATCHES_RESTORE:
        if BALANCE_SIZE_OF_CLASSES:
            train_data = np.load('patches_imgs_balanced.npy')
            train_labels = np.load('patches_labels_balanced.npy')
            train_size = train_labels.shape[0]
        else:
            train_data = np.load('patches_imgs.npy')
            train_labels = np.load('patches_labels.npy')
    else:
        train_data = extract_data(train_data_filename, TRAINING_SIZE)
        train_labels = extract_labels(train_labels_filename, TRAINING_SIZE)
        np.save('patches_imgs',train_data)
        np.save('patches_labels',train_labels)

    print('Total number of patches: ' + str(len(train_data)))
    print('Total number of labels: ' + str(len(train_data)))
    print('Shape of patches: ' + str(train_data.shape))
    print('Shape of labels: ' + str(train_labels.shape))

    num_epochs = NUM_EPOCHS

    c0 = 0
    c1 = 0
    for i in range(len(train_labels)):
        if train_labels[i][0] == 1:
            c0 = c0 + 1
        else:
            c1 = c1 + 1
    print ('Number of data points per class: c0 = ' + str(c0) + ' c1 = ' + str(c1))

    if BALANCE_SIZE_OF_CLASSES:
        if IMG_PATCHES_RESTORE:
            print('Skipping balancing - balanced data already loaded from the disk.')
        else:
            print ('Balancing training data...')
            min_c = min(c0, c1)
            idx0 = [i for i, j in enumerate(train_labels) if j[0] == 1]
            idx1 = [i for i, j in enumerate(train_labels) if j[1] == 1]
            new_indices = idx0[0:min_c] + idx1[0:min_c]
            train_data = train_data[new_indices,:,:,:]
            train_labels = train_labels[new_indices]

            train_size = train_labels.shape[0]
            c0 = 0
            c1 = 0
            for i in range(len(train_labels)):
                if train_labels[i][0] == 1:
                    c0 = c0 + 1
                else:
                    c1 = c1 + 1
            print ('Number of data points per class: c0 = ' + str(c0) + ' c1 = ' + str(c1))
            np.save('patches_imgs_balanced',train_data)
            np.save('patches_labels_balanced',train_labels)

    ##### SETTING UP VALIDATION SET #####
    if VALIDATE:
        perm_indices = np.random.permutation(np.arange(0,len(train_data)))
        validation_data = train_data[perm_indices[0:VALIDATION_SIZE]]
        validation_labels = train_labels[perm_indices[0:VALIDATION_SIZE]]
        print('Size of validation set: ' + str(len(validation_data)))
        print('Shape of validation set: ' + str(validation_data.shape))

    ##### CREATING VARIABLES FOR GRAPH #####
    # This is where training samples and labels are fed to the graph.
    # These placeholder nodes will be fed a batch of training data at each
    # training step using the {feed_dict} argument to the Run() call below.
    train_data_node = tf.placeholder(
        tf.float32,
        shape=(BATCH_SIZE, IMG_PATCH_SIZE, IMG_PATCH_SIZE, NUM_CHANNELS))
    train_labels_node = tf.placeholder(tf.float32,
                                       shape=(BATCH_SIZE, NUM_LABELS))
    train_all_data_node = tf.constant(train_data)

    # The variables below hold all the trainable weights. They are passed an
    # initial value which will be assigned when when we call:
    # {tf.initialize_all_variables().run()}

    conv1_weights = tf.Variable(
        tf.truncated_normal([9, 9, NUM_CHANNELS, 128],  # 5x5 filter, depth 32.
                            stddev=0.1,
                            seed=SEED))
    conv1_biases = tf.Variable(tf.zeros([128]))


    # conv1_weights = tf.Variable(
    #     tf.truncated_normal([5, 5, NUM_CHANNELS, 32],  # 5x5 filter, depth 32.
    #                         stddev=0.1,
    #                         seed=SEED))
    # conv1_biases = tf.Variable(tf.zeros([32]))

    conv2_weights = tf.Variable(
        tf.truncated_normal([7, 7, 128, 64],
                            stddev=0.1,
                            seed=SEED))
    conv2_biases = tf.Variable(tf.constant(0.1, shape=[64]))

    # conv2_weights = tf.Variable(
    #     tf.truncated_normal([5, 5, 32, 64],
    #                         stddev=0.1,
    #                         seed=SEED))
    # conv2_biases = tf.Variable(tf.constant(0.1, shape=[64]))

    conv3_weights = tf.Variable(
        tf.truncated_normal([3, 3, 64, 64],
                            stddev=0.1,
                            seed=SEED))
    conv3_biases = tf.Variable(tf.constant(0.1, shape=[64]))

    fc1_weights = tf.Variable(  # fully connected, depth 512.
        tf.truncated_normal([int((IMG_PATCH_SIZE / 8) * (IMG_PATCH_SIZE / 8) * 64), 512],
                            stddev=0.1,
                            seed=SEED))
    fc1_biases = tf.Variable(tf.constant(0.1, shape=[512]))

    # fc1_weights = tf.Variable(  # fully connected, depth 512.
    #     tf.truncated_normal([int(IMG_PATCH_SIZE / 4 * IMG_PATCH_SIZE / 4 * 64), 512],
    #                         stddev=0.1,
    #                         seed=SEED))
    # fc1_biases = tf.Variable(tf.constant(0.1, shape=[512]))
    fc2_weights = tf.Variable(
        tf.truncated_normal([512, NUM_LABELS],
                            stddev=0.1,
                            seed=SEED))
    fc2_biases = tf.Variable(tf.constant(0.1, shape=[NUM_LABELS]))

    # Make an image summary for 4d tensor image with index idx
    def get_image_summary(img, idx = 0):
        V = tf.slice(img, (0, 0, 0, idx), (1, -1, -1, 1))
        img_w = img.get_shape().as_list()[1]
        img_h = img.get_shape().as_list()[2]
        min_value = tf.reduce_min(V)
        V = V - min_value
        max_value = tf.reduce_max(V)
        V = V / (max_value*PIXEL_DEPTH)
        V = tf.reshape(V, (img_w, img_h, 1))
        V = tf.transpose(V, (2, 0, 1))
        V = tf.reshape(V, (-1, img_w, img_h, 1))
        return V
    
    # Make an image summary for 3d tensor image with index idx
    def get_image_summary_3d(img):
        V = tf.slice(img, (0, 0, 0), (1, -1, -1))
        img_w = img.get_shape().as_list()[1]
        img_h = img.get_shape().as_list()[2]
        V = tf.reshape(V, (img_w, img_h, 1))
        V = tf.transpose(V, (2, 0, 1))
        V = tf.reshape(V, (-1, img_w, img_h, 1))
        return V

    def set_to_zero_if_no_neighbours(mask):
        (height, width) = mask.shape
        for i in range(1, height - 1):
            for j in range(1, width - 1):
                if mask[i][j] == 1 \
                and mask[i + 1][j] == 0 \
                and mask[i - 1][j] == 0 \
                and mask[i][j + 1] == 0 \
                and mask[i][j - 1] == 0:
                    mask[i][j] = 0
                if mask[i][j] == 0 \
                and mask[i + 1][j] == 1 \
                and mask[i - 1][j] == 1 \
                and mask[i][j + 1] == 1 \
                and mask[i][j - 1] == 1:
                    mask[i][j] = 1
        return mask

    def postprocess_prediction(prediction,  width, height):
        mask = prediction_to_mask(prediction, width, height);
        # scipy.misc.imsave('test_before.png', mask)
        mask = set_to_zero_if_no_neighbours(mask)
        # mask = scipy.signal.medfilt(mask, 3)
        # scipy.misc.imsave('test_after.png', mask)
        return mask_to_prediction(mask)
    
    # Get prediction for given input image 
    def get_prediction(img, ):
        data = np.asarray(img_crop(img, IMG_PATCH_SIZE, IMG_PATCH_SIZE, 0))
        data_node = tf.constant(data)
        output = tf.nn.softmax(model(data_node))
        output_prediction = s.run(output)
        output_prediction_postprocessed = postprocess_prediction(output_prediction, int(img.shape[0] / IMG_PATCH_SIZE), int(img.shape[1] / IMG_PATCH_SIZE))

        img_prediction = label_to_img(img.shape[0], img.shape[1], IMG_PATCH_SIZE, IMG_PATCH_SIZE, output_prediction)
        img_prediction_postprocessed = label_to_img(img.shape[0], img.shape[1], IMG_PATCH_SIZE, IMG_PATCH_SIZE, output_prediction_postprocessed)
        return (img_prediction, img_prediction_postprocessed)

    # Get test prediction
    def get_prediction_test(image_idx, overlay = False):
        imageid = "test_%d" % image_idx
        image_filename = test_data_filename + imageid + ".png"
        img = mpimg.imread(image_filename)
        (img_prediction, img_prediction_postprocessed) = get_prediction(img)

        if overlay:
            img_prediction = make_img_overlay(img, img_prediction)
            img_prediction_postprocessed = make_img_overlay(img, img_prediction_postprocessed)
        return (img_prediction, img_prediction_postprocessed)
    
    # Get a concatenation of the prediction and groundtruth for given input file
    def get_prediction_with_groundtruth(filename, image_idx):
        imageid = "satImage_%.3d" % image_idx
        image_filename = filename + imageid + ".png"
        img = mpimg.imread(image_filename)

        (img_prediction,_) = get_prediction(img)
        cimg = concatenate_images(img, img_prediction)

        return cimg

    # Get prediction overlaid on the original image for given input file
    def get_prediction_with_overlay(img_filename, truth_filename, image_idx):
        imageid = "satImage_%.3d" % image_idx
        
        image_filename = img_filename + imageid + ".png"
        img = mpimg.imread(image_filename)

        (img_prediction, img_prediction_postprocessed) = get_prediction(img)

        truth_filename = truth_filename + imageid + ".png"
        img_truth = mpimg.imread(truth_filename)

        oimg = make_img_overlay(img, img_prediction, img_truth)
        oimg_postprocessed = make_img_overlay(img, img_prediction_postprocessed, img_truth)
        return (oimg, oimg_postprocessed)

    def validate(patches, labels):
        print('Validation started.')
        data = np.asarray(patches)
        data_node = tf.constant(data)
        prediction = s.run(tf.nn.softmax(model(data_node)))

        return error_rate(prediction, labels)

    # We will replicate the model structure for the training subgraph, as well
    # as the evaluation subgraphs, while sharing the trainable parameters.
    def model(data, train=False):
        """The Model definition."""
        # 2D convolution, with 'SAME' padding (i.e. the output feature map has
        # the same size as the input). Note that {strides} is a 4D array whose
        # shape matches the data layout: [image index, y, x, depth].
        # LAYER 1
        conv = tf.nn.conv2d(data, conv1_weights, strides=[1, 1, 1, 1], padding='SAME')
        # Bias and rectified linear non-linearity.
        relu = tf.nn.relu(tf.nn.bias_add(conv, conv1_biases))
        # Max pooling. The kernel size spec {ksize} also follows the layout of
        # the data. Here we have a pooling window of 2, and a stride of 2.
        pool = tf.nn.max_pool(relu, ksize=[1, 2, 2, 1], strides=[1, 2, 2, 1], padding='SAME')
        # LAYER 2
        conv2 = tf.nn.conv2d(pool, conv2_weights, strides=[1, 1, 1, 1], padding='SAME')
        relu2 = tf.nn.relu(tf.nn.bias_add(conv2, conv2_biases))
        pool2 = tf.nn.max_pool(relu2, ksize=[1, 2, 2, 1], strides=[1, 2, 2, 1], padding='SAME')
        # LAYER 3
        conv3 = tf.nn.conv2d(pool2, conv3_weights, strides=[1, 1, 1, 1], padding='SAME')
        relu3 = tf.nn.relu(tf.nn.bias_add(conv3, conv3_biases))
        pool3 = tf.nn.max_pool(relu3, ksize=[1, 2, 2, 1], strides=[1, 2, 2, 1], padding='SAME')

        # Uncomment these lines to check the size of each layer
        # print 'data ' + str(data.get_shape())
        # print 'conv ' + str(conv.get_shape())
        # print 'relu ' + str(relu.get_shape())
        # print 'pool ' + str(pool.get_shape())
        # print 'pool2 ' + str(pool2.get_shape())


        # Reshape the feature map cuboid into a 2D matrix to feed it to the
        # fully connected layers.
        pool_shape = pool3.get_shape().as_list()
        reshape = tf.reshape(
            pool3,
            [pool_shape[0], pool_shape[1] * pool_shape[2] * pool_shape[3]])
        # Fully connected layer. Note that the '+' operation automatically
        # broadcasts the biases.
        hidden = tf.nn.relu(tf.matmul(reshape, fc1_weights) + fc1_biases)
        # Add a 50% dropout during training only. Dropout also scales
        # activations such that no rescaling is needed at evaluation time.
        if train:
           hidden = tf.nn.dropout(hidden, 0.5, seed=SEED)
        out = tf.matmul(hidden, fc2_weights) + fc2_biases

        if train == True:
            tf.image_summary('summary_data', get_image_summary(data))
            tf.image_summary('summary_conv', get_image_summary(conv))
            tf.image_summary('summary_pool', get_image_summary(pool))
            tf.image_summary('summary_conv2', get_image_summary(conv2))
            tf.image_summary('summary_pool2', get_image_summary(pool2))
            tf.image_summary('summary_conv3', get_image_summary(conv3))
            tf.image_summary('summary_pool3', get_image_summary(pool3))
        return out

    # Training computation: logits + cross-entropy loss.
    logits = model(train_data_node, True) # BATCH_SIZE*NUM_LABELS
    # print 'logits = ' + str(logits.get_shape()) + ' train_labels_node = ' + str(train_labels_node.get_shape())
    loss = tf.reduce_mean(tf.nn.softmax_cross_entropy_with_logits(
        logits, train_labels_node))
    tf.scalar_summary('loss', loss)

    all_params_node = [conv1_weights, conv1_biases, conv2_weights, conv2_biases, fc1_weights, fc1_biases, fc2_weights, fc2_biases]
    all_params_names = ['conv1_weights', 'conv1_biases', 'conv2_weights', 'conv2_biases', 'fc1_weights', 'fc1_biases', 'fc2_weights', 'fc2_biases']
    all_grads_node = tf.gradients(loss, all_params_node)
    all_grad_norms_node = []
    for i in range(0, len(all_grads_node)):
        norm_grad_i = tf.global_norm([all_grads_node[i]])
        all_grad_norms_node.append(norm_grad_i)
        tf.scalar_summary(all_params_names[i], norm_grad_i)
    
    # L2 regularization for the fully connected parameters.
    regularizers = (tf.nn.l2_loss(fc1_weights) + tf.nn.l2_loss(fc1_biases) +
                    tf.nn.l2_loss(fc2_weights) + tf.nn.l2_loss(fc2_biases))
    # Add the regularization term to the loss.
    # loss += 5e-4 * regularizers

    # # Optimizer: set up a variable that's incremented once per batch and
    # # controls the learning rate decay.
    # batch = tf.Variable(0)
    # # Decay once per epoch, using an exponential schedule starting at 0.01.
    # learning_rate = tf.train.exponential_decay(
    #     0.01,                # Base learning rate.
    #     batch * BATCH_SIZE,  # Current index into the dataset.
    #     train_size,          # Decay step.
    #     0.95,                # Decay rate.
    #     staircase=True)

    batch = tf.Variable(1)
    learning_rate = tf.div(1, batch);
    tf.scalar_summary('learning_rate', learning_rate)
    
    # Use simple momentum for the optimization.
    optimizer = tf.train.MomentumOptimizer(learning_rate, 0.9).minimize(loss, global_step=batch)

    # Predictions for the minibatch, validation set and test set.
    train_prediction = tf.nn.softmax(logits)
    # We'll compute them only once in a while by calling their {eval()} method.
    train_all_prediction = tf.nn.softmax(model(train_all_data_node))

    # Add ops to save and restore all the variables.
    saver = tf.train.Saver()

    # Create a local session to run this computation.
    with tf.Session() as s:
        if RESTORE_MODEL:
            # Restore variables from disk.
            saver.restore(s, FLAGS.train_dir + "/model.ckpt")
            print("Model restored.")

        else:
            # Run all the initializers to prepare the trainable parameters.
            tf.initialize_all_variables().run()

            # Build the summary operation based on the TF collection of Summaries.
            summary_op = tf.merge_all_summaries()
            summary_writer = tf.train.SummaryWriter(FLAGS.train_dir,
                                                    graph=s.graph)
            print ('Initialized!')
            # Loop through training steps.
            print ('Total number of iterations = ' + str(int(num_epochs * train_size / BATCH_SIZE)))

            training_indices = range(train_size)
            start = time.time()
            run_training = True
            iepoch = 0
            while run_training:
            # for iepoch in range(num_epochs):
                # Permute training indices
                perm_indices = np.random.permutation(training_indices)

                for step in range (int(train_size / BATCH_SIZE)):

                    offset = (step * BATCH_SIZE) % (train_size - BATCH_SIZE)
                    batch_indices = perm_indices[offset:(offset + BATCH_SIZE)]

                    # Compute the offset of the current minibatch in the data.
                    # Note that we could use better randomization across epochs.
                    batch_data = train_data[batch_indices, :, :, :]
                    batch_labels = train_labels[batch_indices]
                    # This dictionary maps the batch data (as a np array) to the
                    # node in the graph is should be fed to.
                    feed_dict = {train_data_node: batch_data,
                                 train_labels_node: batch_labels}

                    learning_rate = tf.div(1, batch)
                    if step % RECORDING_STEP == 0:

                        summary_str, _, l, lr, predictions = s.run(
                            [summary_op, optimizer, loss, learning_rate, train_prediction],
                            feed_dict=feed_dict)
                        #summary_str = s.run(summary_op, feed_dict=feed_dict)
                        summary_writer.add_summary(summary_str, step)
                        summary_writer.flush()

                        # print_predictions(predictions, batch_labels)

                        print ('Epoch %d / %d' % (iepoch, num_epochs))
                        print ('Minibatch loss: %.3f, learning rate: %.6f' % (l, lr))
                        print ('Minibatch error: %.1f%%' % error_rate(predictions, batch_labels))
                        end = time.time()
                        print("Time elapsed: %.3f" %(end - start))
                        sys.stdout.flush()
                    else:
                        # Run the graph and fetch some of the nodes.
                        _, l, lr, predictions = s.run(
                            [optimizer, loss, learning_rate, train_prediction],
                            feed_dict=feed_dict)

                # Save the variables to disk.
                save_path = saver.save(s, FLAGS.train_dir + "/model.ckpt")
                print("Model saved in file: %s" % save_path)
                iepoch += 1
                if (TERMINATE_AFTER_TIME and time.time() - start > MAX_TRAINING_TIME_IN_SEC):
                    run_training = False;
                if (not TERMINATE_AFTER_TIME and iepoch >= NUM_EPOCHS):
                    run_training = False;



        if VISUALIZE_PREDICTION_ON_TRAINING_SET:
            print ("Visualizing prediction on training set")
            prediction_training_dir = "predictions_training/"
            if not os.path.isdir(prediction_training_dir):
                os.mkdir(prediction_training_dir)
            limit = TRAINING_SIZE + 1 if VISUALIZE_NUM == -1 else VISUALIZE_NUM
            for i in range(1, limit):
                print ("Image: " + str(i))
                # pimg = get_prediction_with_groundtruth(train_data_filename, i)
                # Image.fromarray(pimg).save(prediction_training_dir + "prediction_" + str(i) + ".png")
                (oimg, oimg_postprocessed) = get_prediction_with_overlay(train_data_filename, train_labels_filename, i)
                oimg.save(prediction_training_dir + "overlay_" + str(i) + ".png")
                oimg_postprocessed.save(prediction_training_dir + "overlay_" + str(i) + "_postprocessed.png")
        
        if VALIDATE:
            err = validate(validation_data, validation_labels)
            print('Validation error: %.1f%%' % err)

        if RUN_ON_TEST_SET:
            print ("Running prediction on test set")
            prediction_test_dir = "predictions_test/"
            if not os.path.isdir(prediction_test_dir):
                os.mkdir(prediction_test_dir)

            with open('submission.csv', 'w') as csvfile:
                writer = csv.writer(csvfile, delimiter=',')
                writer.writerow(['id','prediction'])
                for i in range(1, TEST_SIZE + 1):
                    print("Test img: " + str(i))
                    # Visualization
                    (pimg, pimg_postprocessed) = get_prediction_test(i, True)
                    pimg.save(prediction_test_dir + "test" + str(i) + ".png")
                    pimg_postprocessed.save(prediction_test_dir + "test" + str(i) + "_postprocessed.png")

                    # Construction of the submission file
                    (_,prediction) = get_prediction_test(i);
                    prediction = prediction.astype(np.int)
                    num_rows = prediction.shape[0]
                    num_cols = prediction.shape[1]
                    rows_out = np.empty((0,2))
                    for x in range(0, num_rows, IMG_PATCH_SIZE):
                        for y in range(0, num_cols, IMG_PATCH_SIZE):
                            id = str(i).zfill(3) + "_" + str(x) + "_" + str(y)
                            next_row = np.array([[id, str(prediction[y,x])]])
                            rows_out = np.concatenate((rows_out, next_row))
                    writer.writerows(rows_out)
            csvfile.close()

if __name__ == '__main__':
    tf.app.run()
