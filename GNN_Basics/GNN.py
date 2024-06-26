# !pip install torch-scatter
# !pip install torch-cluster
# !pip install torch-sparse
# !pip install torch-geometric
# !pip install tensorboardX

import numpy as np
from datetime import datetime
import torch

import torch.optim as optim
import torch.nn as nn
import torch.nn.functional as F

# nn module for Neural Network model
# Implement graph conv, gene conf etc.
import torch_geometric.nn as pyg_nn

# Performs some graph utlity functions
import torch_geometric.utils as pyg_utils

# For graph visualization
import networkx as nx
import torch_geometric.transforms as T

# Way to track our training and how well we perform over time
from tensorboardX import SummaryWriter

# to get node embeddings into 2d representation
from sklearn.manifold import TSNE
import matplotlib.pyplot as plt

# Datasets we will use
from torch_geometric.datasets import TUDataset
from torch_geometric.datasets import Planetoid
from torch_geometric.data import DataLoader


class GCN(nn.Module):
    def __init__(
        self, input_dim, hidden_dim, out_dim, conv_layers=2, doutrate=0.25, task="node"
    ):
        super(GCN, self).__init__()

        self.task = task
        self.doutrate = doutrate
        self.conv_layers = conv_layers

        # Module list for convolutional layers
        self.convs = nn.ModuleList()
        # Add first layer with input_dim -> hidden_dim
        self.convs.append(self.build_conv_model(input_dim, hidden_dim))

        # Add more layers with hidden_dim -> hidden_dim
        for i in range(conv_layers):
            self.convs.append(self.build_conv_model(hidden_dim, hidden_dim))

        # Post message passing defined by MLP
        self.post_mp = nn.Sequential(
            nn.Linear(hidden_dim, hidden_dim),
            nn.Dropout(doutrate),
            nn.Linear(hidden_dim, out_dim),
        )

        # Number of total layers
        self.num_layers = self.conv_layers + 1

    # Build convolutional blocks
    def build_conv_model(self, input_dim, hidden_dim):
        # If we perform node classification, we use simple graph convolution
        if self.task == "node":
            # here we could use our CustomConv.py
            return pyg_nn.GCNConv(input_dim, hidden_dim)
        # GIN is more powerful to structural learning
        else:
            return pyg_nn.GINConv(
                nn.Sequential(
                    nn.Linear(input_dim, hidden_dim),
                    nn.ReLU(),
                    nn.Linear(hidden_dim, hidden_dim),
                )
            )

    def forward(self, data):
        # Data consists of: data.x (feature matrix), data.edge_index (adjecency matrix, what are the edges),
        # data.batch (which node belongs to which graph)

        x, edge_index, batch = data.x, data.edge_index, data.batch

        # Sanity check:
        if data.num_node_features == 0:
            # if no features, we use constant feature
            x = torch.ones(data.num_nodes, 1)

        for i in range(self.num_layers):
            # Input to GCN is (node features (|V|, F_in), edge indices (2,E))
            # Output: node features (|V|, F_out)

            # Call the convolutional layer
            x = self.convs[i](x, edge_index)

            emb = x

            # Apply activation function and dropout
            x = F.relu(x)
            x = F.dropout(x, p=self.doutrate, training=self.training)

        # If we do graph classification we need pooling (mean or max)
        if self.task == "graph":
            # x = pyg_nn.global_mean_pool(x, batch)
            x = pyg_nn.global_max_pool(x, batch)

        x = self.post_mp(x)

        # Do log softmax for crossentropy
        # return embedding for visualization
        return emb, F.log_softmax(x, dim=1)

    def loss(self, pred, label):
        # Since we return log softmax we need to return negative log likelihood
        return F.nll_loss(pred, label)


# Train the model
def train(dataset, task, conv_layer, writer, epochs):

    # Based on the task we split the dataset
    if task == "graph":
        data_size = len(dataset)
        loader = DataLoader(
            dataset[: int(data_size * 0.8)], batch_size=64, shuffle=True
        )
        test_loader = DataLoader(
            dataset[int(data_size * 0.8) :], batch_size=64, shuffle=True
        )

    else:
        # Data loader definition for node classification
        test_loader = loader = DataLoader(dataset, batch_size=64, shuffle=True)

    # Build the model
    model = GCN(
        max(dataset.num_node_features, 1),
        32,
        dataset.num_classes,
        conv_layers=conv_layer,
        task=task,
    )

    # Define optimizer
    opt = optim.Adam(model.parameters(), lr=0.01)

    for epoch in range(0, epochs):
        total_loss = 0
        model.train()

        for batch in loader:

            opt.zero_grad()

            embedding, pred = model(batch)

            label = batch.y

            # Filter training mask and labels only for node classification
            if task == "node":
                pred = pred[batch.train_mask]
                label = label[batch.train_mask]

            loss = model.loss(pred, label)

            loss.backward()

            opt.step()

            # Accumulate loss
            total_loss += loss.item() * batch.num_graphs

        # Average loss
        total_loss /= len(loader.dataset)

        # Write loss to tensorboard
        writer.add_scalar("Loss", total_loss, epoch)

        # Evaluate the model every 10 epochs on the test set
        if epoch % 10 == 0:
            test_acc = test(test_loader, model)
            print(
                "Epoch {}. Loss {:.4f}. Test accuracy {:.4f}".format(
                    epoch, total_loss, test_acc
                )
            )

            # Write test accuracy to tensorboard
            writer.add_scalar("test accuracy", test_acc, epoch)

    return model


# Test the model
def test(loader, model, is_validation=False):
    model.eval()

    correct = 0
    for data in loader:
        with torch.no_grad():

            embeddings, pred = model(data)

            pred = pred.argmax(dim=1)

            label = data.y

        if model.task == "node":
            # Get the mask for the validation or test set
            mask = data.val_mask if is_validation else data.test_mask

            # Node classification: only evaluate in test set
            pred = pred[mask]
            label = data.y[mask]

        correct += pred.eq(label).sum().item()

    if model.task == "graph":
        total = len(loader.dataset)
    else:
        total = 0
        for data in loader.dataset:
            total += torch.sum(data.test_mask).item()
    return correct / total


# Cluster the node embeddings
def visualization_nodembs(dataset, model):

    color_list = ["red", "orange", "green", "blue", "purple", "brown", "black"]
    loader = DataLoader(dataset, batch_size=64, shuffle=True)

    embs = []
    colors = []

    for batch in loader:
        emb, pred = model(batch)

        embs.append(emb)

        colors += [color_list[y] for y in batch.y]

    embs = torch.cat(embs, dim=0)

    # Perform t-SNE to reduce the dimensionality to 2D
    xs, ys = zip(*TSNE().fit_transform(embs.detach().numpy()))

    # Scatter plot of the embeddings colored by the ground truth
    plt.scatter(xs, ys, color=colors)
    plt.show()


if __name__ == "__main__":

    # Node classification
    writer = SummaryWriter("GNN_Basics/log/" + datetime.now().strftime("%Y%m%d-%H%M%S"))
    dataset = Planetoid(root="/tmp/cora", name="cora")
    task = "node"
    conv_layer = 6
    model = train(dataset, task, conv_layer, writer, 100)
    visualization_nodembs(dataset, model)
