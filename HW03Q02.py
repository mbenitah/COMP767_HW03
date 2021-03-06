import os
import sys
import gym
import pickle
import argparse
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker

import torch
import torch.nn as nn
import torch.optim as optim
import torch.nn.functional as F

from torch.distributions import Categorical

from tqdm import tqdm
from datetime import datetime

SEED = None
GAMMA = 0.9
ALPHAS = [0.01, 0.001, 0.0001]
HIDDEN_SIZE = [32, 64, 128]
RUNS = 5
EPISODES = 2000
MAX_STEPS = 200
UPDATE_EVERY = 10
ENV = 'CartPole-v0'
SAVED_MODELS_FOLDER = './data/'
NOW = "{0:%Y-%m-%dT%H-%M-%S}".format(datetime.now())

# #############################################################################
#
# Parser
#
# #############################################################################


def get_arguments():

    parser = argparse.ArgumentParser(
        description='Controlling a gym environment with Sarsa(lambda).')

    parser.add_argument('--seed', type=int, default=SEED,
                        help='Seed for the random number generator.')
    parser.add_argument('--env', type=str, default=ENV,
                        help='The environment to be used. Default: '
                        + ENV)
    parser.add_argument('--gamma', type=float, default=GAMMA,
                        help='Defines the discount rate. Default: '
                        + str(GAMMA))
    parser.add_argument('--alphas', type=float, default=ALPHAS,
                        nargs='*',
                        help='The learning rates to be used for the '
                        'policy. More than one value can be specified if '
                        'separated by spaces. Default: ' + str(ALPHAS))
    parser.add_argument('-s', '--hidden_size', type=int, default=HIDDEN_SIZE,
                        nargs='*',
                        help='Size of the hidden layer. '
                        'Default: ' + str(HIDDEN_SIZE))
    parser.add_argument('-n', '--runs', type=int, default=RUNS,
                        help='Number of runs to be executed. Default: '
                        + str(RUNS))
    parser.add_argument('-e', '--episodes', type=int,
                        default=EPISODES,
                        help='Number of episodes to be executed in a single '
                        'run. Default: ' + str(EPISODES))
    parser.add_argument('--max_steps', type=int, default=MAX_STEPS,
                        help='Number of maximum steps allowed in a single '
                        'episode. Default: ' + str(MAX_STEPS))
    parser.add_argument('-u', '--update_every', type=int, default=UPDATE_EVERY,
                        help='Number of episodes to run before every weight '
                        'update. Default: ' + str(UPDATE_EVERY))
    parser.add_argument('-v', '--verbose', action="store_true",
                        help='If this flag is set, the algorithm will '
                        'generate more output, useful for debugging.')
    parser.add_argument('-r', '--render', action="store_true",
                        help='If this flag is set, each episode will be '
                        'rendered.')
    parser.add_argument('-l', '--load', type=str, default=None,
                        help='Filename of a .pickle pre-saved data file saved '
                        'in the {} folder. Please include the .pickle '
                        'extension.'.format(SAVED_MODELS_FOLDER))

    return parser.parse_args()


# #############################################################################
#
# Plotting
#
# #############################################################################


def plot9(title, steps_rf, steps_ac):
    '''Creates 9 plots for different combinations of the
    hyperparameters.'''

    fig, axs = plt.subplots(nrows=3, ncols=3,
                            constrained_layout=True,
                            sharey=True,
                            figsize=(10, 10))

    fig.suptitle(title, fontsize=12)
    i = 0
    for hs_idx, hs in enumerate(args.hidden_size):
        for alpha_idx, alpha in enumerate(args.alphas):
            plot_learning_curves(axs[hs_idx, alpha_idx], steps_rf, steps_ac, hs_idx, alpha_idx)
            axs[hs_idx, alpha_idx].set_xlabel('Episodes')
            axs[hs_idx, alpha_idx].set_ylabel('Number of steps')
            axs[hs_idx, alpha_idx].set_title('Hidden layer size: {}\nLearning rate: {}'.format(hs, alpha))
            axs[hs_idx, alpha_idx].legend()
            i += 1
            if i == 9: break
    plt.show()


def plot_learning_curves(ax, steps_rf, steps_ac, hidden_idx, alpha_idx):
    '''Plots the number of steps per episode.

    Input:
    ax          : the target axis object
    steps_rf    : array of shape
                  (len(sizes), len(alphas), args.runs, args.episodes)
                  containing the number of steps for each hidden_size, alpha, run,
                  episode for reinforce method
    steps_ac    : array of shape
                  (len(sizes), len(alphas), args.runs, args.episodes)
                  containing the number of steps for each hidden_size, alpha, run,
                  episode for actor-critic method
    hidden_idx  : index of the hidden_size
    alpha_idx   : index of the learning rate alpha'''

    x_values = np.arange(1, args.episodes + 1)

    data = steps_rf[hidden_idx, alpha_idx, :, :]
    plot_line_variance(
        ax,
        x_values,
        data,
        label='Reinforce',
        color='C0',
        axis=0
    )

    data = steps_ac[hidden_idx, alpha_idx, :, :]
    plot_line_variance(
        ax,
        x_values,
        data,
        label='Actor-Critic',
        color='C1',
        axis=0
    )



def plot_line_variance(ax, x_values, data, label, color, axis=0, delta=1):
    '''Plots the average data for each time step and draws a cloud
    of the standard deviation around the average.

    Input:
    ax      : axis object where the plot will be drawn
    x_values: x-axis labels
    data    : data of shape (num_trials, timesteps)
    color   : the color to be used
    delta   : (optional) scaling of the standard deviation around the average
              if ommitted, delta = 1.'''

    avg = np.average(data, axis)
    std = np.std(data, axis)

    # min_values = np.min(data, axis)
    # max_values = np.max(data, axis)

    # ax.plot(min_values, color + '--', linewidth=0.5)
    # ax.plot(max_values, color + '--', linewidth=0.5)

    ax.fill_between(x_values,
                    avg + delta * std,
                    avg - delta * std,
                    facecolor=color,
                    alpha=0.5)
    # ax.plot(x_values, avg, label=label, color=color, marker='.')
    ax.plot(x_values, avg, label=label, color=color)

# #############################################################################
#
# Rewards
#
# #############################################################################


def discount_rewards(rewards):
    returns = []
    R = 0

    # calculate discounted rewards from inversed array
    for r in rewards[::-1]:
        # calculate the discounted value
        R = r + args.gamma * R
        # insert in the beginning of the list
        # (the list is once again in the correct order)
        returns.insert(0, R)

    return returns

# #############################################################################
#
# Model
#
# #############################################################################


class Policy(nn.Module):
    def __init__(self, agent, input_dim, output_dim, hidden_size, alpha):
        super(Policy, self).__init__()

        self.hidden = nn.Linear(input_dim, hidden_size)

        # actor
        self.action_head = nn.Linear(hidden_size, output_dim)

        # critic
        self.value_head = nn.Linear(hidden_size, 1)

        self.actions = []
        self.rewards = []

        self.optimizer = torch.optim.Adam(self.parameters(), lr=alpha)

        if agent == 'ac':
            self.backprop = self.backprop_ac
        else:
            self.backprop = self.backprop_rf

    def forward(self, x):

        x = F.relu(self.hidden(x))

        action_prob = F.softmax(self.action_head(x), dim=-1)
        value = self.value_head(x)

        return action_prob, value

    def choose_action(self, state):
        state = torch.from_numpy(state).float()
        probs, value = self(state)

        # get categorical distribution from probabilities
        # and sample an action
        distr = Categorical(probs)
        action = distr.sample()

        # save to action buffer
        self.actions.append([distr.log_prob(action), value])

        return action.item()

    def backprop_rf(self):
        '''Calculate losses and do gradient backpropagation.
        This code for the reinforce method complety ignores the
        value branch of the network, and back propagates over
        the policy.'''

        policy_losses = []

        # discount rewards and normalise returns
        returns = discount_rewards(self.rewards)
        returns = torch.tensor(returns)
        returns = (returns - returns.mean()) / (returns.std() + eps)

        # calculate losses
        for (log_prob, value), R in zip(self.actions, returns):

            # actor loss (negative log-likelihood)
            policy_losses.append(-log_prob * R)

        # sum up all the values of policy_losses and value_losses
        loss = torch.stack(policy_losses).sum()

        # backprop
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        # reset buffers
        del self.rewards[:]
        del self.actions[:]

    def backprop_ac(self):
        '''Calculate losses and do gradient backpropagation
        for the actor-critic (reinforce with baseline) method.'''

        policy_losses = []
        value_losses = []

        # discount rewards and normalise returns
        returns = discount_rewards(self.rewards)
        returns = torch.tensor(returns)
        returns = (returns - returns.mean()) / (returns.std() + eps)

        # calculate losses
        for (log_prob, value), R in zip(self.actions, returns):
            advantage = R - value.item()

            # actor loss (negative log-likelihood)
            policy_losses.append(-log_prob * advantage)

            # critic loss using L1 smooth loss
            value_losses.append(F.smooth_l1_loss(value, torch.tensor([R])))

        # sum up all the values of policy_losses and value_losses
        loss = torch.stack(policy_losses).sum() + torch.stack(value_losses).sum()

        # backprop
        self.optimizer.zero_grad()
        loss.backward()
        self.optimizer.step()

        # reset buffers
        del self.rewards[:]
        del self.actions[:]

# #############################################################################
#
# Runs
#
# #############################################################################


def one_run(agent, hidden_size, alpha, seed=None):

    n_episodes = args.episodes
    update_every = args.update_every
    gamma = args.gamma
    scores = []

    assert 0 <= gamma <= 1
    assert alpha > 0

    env = gym.make(args.env)
    env.seed(args.seed)

    # env._max_episode_steps = args.max_steps

    input_dim = env.observation_space.shape[0]
    output_dim = env.action_space.n

    model = Policy(agent, input_dim, output_dim, hidden_size, alpha)

    for episode in range(args.episodes):

        # reset environment and episode reward
        state = env.reset()
        steps = 0
        done = False

        while not done:

            # select action from policy
            action = model.choose_action(state)

            # take the action
            state, reward, done, _ = env.step(action)

            if args.render:
                env.render()

            model.rewards.append(reward)
            steps += 1

        scores.append(steps)
        model.backprop()

        # log results
        if episode % args.update_every == 0:
            print('Episode {}\tLast reward: {:.2f}\tAverage reward: {:.2f}'.format(
                  episode, steps, np.mean(scores[-args.update_every:])))

    return scores


def runs(agent, sizes, alphas):
    '''Performs multiple runs (as defined by parameter --runs)
    for a list of parameters alpha and a list of parameter alphas_w.

    Input:
    agent     : the agent to be used
    sizes     : sizes of the hidden layer
    alphas    : list of alpha_t (learning rates)

    Output:
    array of shape (len(sizes), len(alphas), args.runs, args.episodes)
    containing the number of steps for each alpha, run, episode
    '''

    steps = np.empty((len(sizes), len(alphas), args.runs, args.episodes))

    for size_idx, hidden_size in enumerate(sizes):
        for alpha_idx, alpha in enumerate(alphas):
            for run in tqdm(range(args.runs)):
                # sets a new seed for each run
                seed = np.random.randint(0, 2**32 - 1)
                print('Agent: {}\tHidden size: {}\tLearning rate: {}'.format(agent, hidden_size, alpha))
                steps[size_idx, alpha_idx, run, :] = one_run(
                    agent,
                    hidden_size,
                    alpha,
                    seed
                )

    return steps


# #############################################################################
#
# Main
#
# #############################################################################


# global variables
args = get_arguments()
eps = np.finfo(np.float32).eps.item()


def save(objects, filename):
    f = open(os.path.join(SAVED_MODELS_FOLDER,
                          NOW + '_' + filename + '.pickle'), 'wb')
    pickle.dump(objects, f)
    f.close()


def load(filename):
    # try to open in current folder or full path
    try:
        f = open(filename, 'rb')
        steps_rf, steps_ac, args = pickle.load(f)
        f.close()
    except FileNotFoundError:
        # try to open file in the data folder
        filename = os.path.join(SAVED_MODELS_FOLDER, filename)
        load(filename)
        print('Could not open file {}'.format(filename))
        sys.exit()

    return steps_rf, steps_ac, args


def main():
    global args

    # sets the seed for random experiments
    np.random.seed(args.seed)
    if args.seed is not None:
        torch.manual_seed(args.seed)

    # env._max_episode_steps = args.max_steps

    alphas = args.alphas

    if args.load is not None:
        # load pre-saved data
        filename = args.load
        steps_rf, steps_ac, args = load(filename)
        print('Using saved data from: {}'.format(filename))
    else:
        steps_rf = runs('rf', args.hidden_size, alphas)
        steps_ac = runs('ac', args.hidden_size, alphas)
        save([steps_rf, steps_ac, args], 'steps')

    plot9('Learning curves', steps_rf, steps_ac)


if __name__ == '__main__':
    main()
