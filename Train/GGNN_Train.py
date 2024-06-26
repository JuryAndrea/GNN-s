# from paper: GATED GRAPH SEQUENCE NEURAL NETWORKS
# "The biggest modification of GNNs is that the authors use Gated Recurrent Units
# (Cho et al., 2014) and unroll the recurrence for a fixed number of steps T
# and use backpropagation through time in order to compute gradients."

# Based on the following tutorial: https://github.com/AntonioLonga/PytorchGeometricTutorial/tree/main/Tutorial9

import os
import os.path as osp
import torch
import torch.nn as nn
import torch.nn.functional as F
import torch_geometric.transforms as T
from torch_geometric.datasets import Planetoid, TUDataset
from torch_geometric.data import DataLoader
from torch_geometric.nn.inits import uniform
from torch_geometric.nn.conv import MessagePassing
from torch.nn import Parameter as Param
from torch import Tensor
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt
import numpy as np
from datetime import datetime

# For CPU/GPU UILITZATION
import json
import os
import sys
from time import time
import psutil
from compstats import computeStats


torch.manual_seed(42)


# region Gated Graph Conv
# BASE Class for information propagation and update amongst nodes
class GatedGraphConv(MessagePassing):

    def __init__(self, out_channels, num_layers, aggr="add", bias=True, **kwargs):
        super(GatedGraphConv, self).__init__(aggr=aggr, **kwargs)

        self.out_channels = out_channels
        self.num_layers = num_layers

        self.rnn = torch.nn.GRUCell(self.out_channels, self.out_channels, bias=bias)
        self.weight = Param(
            Tensor(self.num_layers, self.out_channels, self.out_channels)
        )

        self.reset_parameters()

    def reset_parameters(self):
        uniform(self.out_channels, self.weight)
        self.rnn.reset_parameters()

    def forward(self, x):

        edge_index = data.edge_index
        edge_weight = data.edge_attr

        if x.size(-1) > self.out_channels:
            raise ValueError(
                "The number of input channels is not allowed to "
                "be larger than the number of output channels"
            )

        # Create padding in case input is smaller than output
        if x.size(-1) < self.out_channels:
            zero = x.new_zeros(x.size(0), self.out_channels - x.size(-1))
            x = torch.cat([x, zero], dim=1)

        for i in range(self.num_layers):
            m = torch.matmul(x, self.weight[i])

            # Propagation model based on point 3.2 of paper
            m = self.propagate(edge_index, x=m, edge_weight=edge_weight, size=None)
            x = self.rnn(m, x)

        return x

    def __repr__(self):
        return "{}({}, num_layers={})".format(
            self.__class__.__name__, self.out_channels, self.num_layers
        )


# endregion
# region MLP
class MLP(nn.Module):
    def __init__(self, input_dim, hid_dims):
        super(MLP, self).__init__()

        # Create the sequential model
        self.mlp = nn.Sequential()
        # List of dimensions
        dims = [input_dim] + hid_dims
        for i in range(len(dims) - 1):
            self.mlp.add_module(
                "lay_{}".format(i),
                nn.Linear(in_features=dims[i], out_features=dims[i + 1]),
            )
            if i + 1 < len(dims):
                self.mlp.add_module("act_{}".format(i), nn.Tanh())

    def reset_parameters(self):
        for i, l in enumerate(self.mlp):
            if type(l) == nn.Linear:
                nn.init.xavier_normal_(l.weight)

    def forward(self, x):
        return self.mlp(x)


# endregion


# region GGNN
class GGNN(torch.nn.Module):
    def __init__(
        self,
        in_channels,
        out_channels=None,
        num_conv=3,
        hidden_dim=32,
        aggr="add",
        mlp_hdim=32,
        mlp_hlayers=3,
    ):
        super(GGNN, self).__init__()
        self.emb = lambda x: x
        self.best_acc = -1

        if out_channels is None:
            out_channels = in_channels

        if in_channels != out_channels:
            print("mismatch, operating a reduction")
            self.emb = nn.Linear(in_channels, hidden_dim, bias=False)

        self.conv = GatedGraphConv(out_channels=out_channels, num_layers=num_conv)

        self.mlp = MLP(input_dim=out_channels, hid_dims=[mlp_hdim] * mlp_hlayers)

        self.out_layer = nn.Linear(mlp_hdim, dataset.num_classes)

    def forward(self, data):

        # Linear Encoding / Feature Reduction
        x = self.emb(data.x)

        # Propagation and GRU
        x = self.conv(x)

        # MLP
        x = self.mlp(x)

        # Linear Decoding
        x_emb = self.out_layer(x)

        # Prediction
        return x_emb, F.log_softmax(x_emb, dim=-1)


# endregion

# region Training


def train(dataset, epochs=100, num_conv=3, learning_rate=0.001):
    ###### SETUP ######
    start_time = time()
    test_loader = loader = DataLoader(dataset, batch_size=1, shuffle=True)
    model = GGNN(
        in_channels=dataset.x.shape[-1], out_channels=32, num_conv=num_conv
    ).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    loss_fn = nn.CrossEntropyLoss()
    tot_loss = 0
    best_acc = [0, 0, 0]
    
    # For CPU/GPU UILITZATION
    current_filename = os.path.abspath(__file__).split("/")[-1]
    
    requirements = {}

    # Reimport Dictionary to resume execution
    #file_path = os.path.join(os.path.pardir, "ADGN_Message.py_requirements.json")
    file_path = 'Train/comp_per_model/GGNN.py_requirements.json'
    if os.path.exists(file_path):
        print("[WARNING]\n Importing an already existing json file for the requirements dictionary")
        print(file_path)
        # Open the file and load the data
        with open(file_path, 'r') as file:
            requirements = json.load(file)
    else:
        print(current_filename)
        current_filename + "_requirements.json"
    
    
    pid = os.getpid()
    # Get the psutil Process object using the PID
    current_process = psutil.Process(pid)
    num_cpus = psutil.cpu_count()
    
    start_time = time()
    computeStats(start_time,-1, current_process, -1, requirements)
    
    ###########################
    

    print("#" * 100 + "\n")
    print("[MODEL REPRESENTATION]", repr(model))
    print(
        "#" * 20
        + f" Running Gated GNN, with {str(epochs)} epochs, {str(num_conv)} convs "
        + "#" * 20
    )
    ####################

    for epoch in range(1, epochs + 1):
        print(f"Processing Epoch {epoch}", end="\r")
        epoch_start_time = datetime.now()
        model.train()
        
        # For CPU/GPU UILITZATION
        computeStats(start_time, epoch-1, current_process, num_cpus, requirements)

        for batch in loader:
            optimizer.zero_grad()

            # Forward pass
            emb_x, pred = model(batch)

            # extract prediction and label
            pred = pred[batch.train_mask]
            label = batch.y[batch.train_mask]

            loss = loss_fn(pred, label)
            loss_fn(pred, label).backward()

            optimizer.step()
            tot_loss += loss.item()

        tot_loss /= len(loader.dataset)
        ###

        ### Test
        if epoch % 10 == 0:
            model.eval()
            for data in test_loader:
                with torch.no_grad():
                    accs = []
                    # Forward pass
                    emb, logits = model(data)
                    masks = [data.train_mask, data.val_mask, data.test_mask]
                    for mask in masks:

                        # Obtain most likely class
                        pred = logits[mask].max(1)[1]

                        # Compute accuracy
                        acc = pred.eq(data.y[mask]).sum().item() / mask.sum().item()
                        accs.append(acc)

                # Collecting and computing best accuracies for each set
                train_acc = accs[0]
                val_acc = accs[1]
                test_acc = accs[2]

                best_acc[0] = max(best_acc[0], train_acc)
                best_acc[1] = max(best_acc[1], val_acc)
                best_acc[2] = max(best_acc[2], test_acc)

                model.best_acc = best_acc[2]

            print(
                "Epoch: {:03d}, Train Acc: {:.0%}, "
                "Val Acc: {:.0%}, Test Acc: {:.0%}, time for 10 epochs {:.2f}".format(
                    epoch, train_acc, val_acc, test_acc, epoch_start_time
                )
            )

    print("Training Completed in {:.2f} seconds".format(time() - start_time))
    print(
        "Best Accuracies Train Acc: {:.0%}, Val Acc: {:.0%}, Test Acc: {:.0%}".format(
            best_acc[0], best_acc[1], best_acc[2]
        )
    )
    
    # For CPU/GPU UILITZATION
    with open(file_path, "w") as json_file:
        json.dump(requirements, json_file, indent=4)

    return model


# endregion


# region Visualisation
def visualization_nodembs(dataset, model):
    color_list = ["red", "orange", "green", "blue", "purple", "brown", "black"]
    loader = DataLoader(dataset, batch_size=1, shuffle=False)
    embs = []
    colors = []

    for batch in loader:
        print("batch is", batch)
        emb, pred = model(batch)
        embs.append(emb)

        colors += [color_list[y] for y in batch.y]
    embs = torch.cat(embs, dim=0)

    # Get the 2D representation of the embeddings
    xs, ys = zip(*TSNE(random_state=42).fit_transform(embs.detach().numpy()))

    # Plot the 2D representation
    plt.scatter(xs, ys, color=colors)
    plt.title(
        f"GGNN, #epoch:{str(args.epoch)}, #conv:{str(args.conv)}\n accuracy:{model.best_acc*100}%"
    )
    plt.show()


# endregion

### Flags Areas ###
import argparse

parser = argparse.ArgumentParser(description="Process some inputs.")
parser.add_argument("--epoch", type=int, help="Epoch Amount", default=100)
parser.add_argument("--conv", type=int, help="Conv Amount", default=3)

device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
device = "cpu"

dataset = "PubMed"
transform = T.Compose(
    [
        T.TargetIndegree(),
    ]
)
path = osp.join("data", dataset)
dataset = Planetoid(path, dataset, transform=transform)

data = dataset[0]

print("[DATA],", data)


# region Execution
if __name__ == "__main__":

    test_dataset = dataset[: len(dataset) // 10]
    train_dataset = dataset[len(dataset) // 10 :]
    test_loader = DataLoader(test_dataset)
    train_loader = DataLoader(train_dataset)

    args = parser.parse_args()

    epochs = args.epoch
    convs = args.conv

    model = train(dataset, epochs=epochs, num_conv=convs, learning_rate=0.001)
    model.__repr__()
    visualization_nodembs(dataset, model)

# endregion
