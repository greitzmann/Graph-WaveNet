import torch.optim as optim
from model import *
import util
import math


def cyclical_lr(stepsize, min_lr=3e-4, max_lr=3e-3):

    # Scaler: we can adapt this if we do not want the triangular CLR
    scaler = lambda x: 1.

    # Lambda function to calculate the LR
    lr_lambda = lambda it: min_lr + (max_lr - min_lr) * relative(it, stepsize)

    # Additional function to see where on the cycle we are
    def relative(it, stepsize):
        cycle = math.floor(1 + it / (2 * stepsize))
        x = abs(it / stepsize - 2 * cycle + 1)
        return max(0, (1 - x)) * scaler(cycle)

    return lr_lambda

class Trainer():
    def __init__(self, model, scaler, lrate, wdecay, clip=5, lr_decay_rate=.97, fp16=''):
        self.model = model
        self.optimizer = optim.Adam(self.model.parameters(), lr=lrate, weight_decay=wdecay)
        self.scaler = scaler
        self.clip = clip
        self.fp16 = fp16
        #l1 = lambda epoch: lr_decay_rate ** epoch
        self.scheduler = optim.lr_scheduler.CyclicLR(self.optimizer, base_lr=lrate/10, max_lr=lrate,cycle_momentum=False)
        if self.fp16:
            try:
                from apex import amp  # Apex is only required if we use fp16 training
            except ImportError:
                raise ImportError("Please install apex from https://www.github.com/nvidia/apex to use fp16 training.")
            amp.register_half_function(torch, 'einsum')
            self.model, self.optimizer = amp.initialize(self.model, self.optimizer,
                                                            opt_level=self.fp16)

    def train(self, input, real_val):
        self.model.train()
        self.optimizer.zero_grad()
        input = nn.functional.pad(input,(1,0,0,0))
        output = self.model(input).transpose(1,3)  # now, output = [batch_size,1,num_nodes,12]

        #torch.clamp(output, 0, 70)

        predict = self.scaler.inverse_transform(output)
        real = torch.unsqueeze(real_val, dim=1)
        mae, mape, rmse = util.calc_metrics(predict, real, null_val=0.0)

        if self.fp16:
            from apex import amp
            with amp.scale_loss(mae, self.optimizer) as scaled_loss:
                scaled_loss.backward()
            torch.nn.utils.clip_grad_norm_(amp.master_params(self.optimizer), self.clip)
        else:
            mae.backward()
            if self.clip is not None:
                torch.nn.utils.clip_grad_norm_(self.model.parameters(), self.clip)
        self.optimizer.step()
        return mae.item(),mape.item(),rmse.item()

    def eval(self, input, real_val):
        self.model.eval()
        input = nn.functional.pad(input,(1,0,0,0))
        output = self.model(input).transpose(1,3) #  [batch_size,12,num_nodes,1]
        real = torch.unsqueeze(real_val,dim=1)
        predict = self.scaler.inverse_transform(output)
        predict = torch.clamp(predict, min=0., max=70.)
        mae, mape, rmse = [x.item() for x in util.calc_metrics(predict, real, null_val=0.0)]
        return mae, mape, rmse
