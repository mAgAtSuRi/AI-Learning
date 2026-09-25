from math import log
import torch
import torch.nn.functional as F
import matplotlib.pyplot as plt
import random

words = open("names.txt", 'r').read().splitlines()

chars = sorted(list(set(''.join(words))))

stoi = {s: i+1 for i, s in enumerate(chars)}
stoi['.'] = 0
itos = {i: s for s, i in stoi.items()}

#Build the dataset
block_size = 3 # How many characters do we take to predict the next one

def build_dataset(words):
	X, Y = [], []
	for w in words:
		context = [0] * block_size
		for ch in w + '.':
			ix = stoi[ch]
			X.append(context)
			Y.append(ix)
			context = context[1:] + [ix]

	X = torch.tensor(X)
	Y = torch.tensor(Y)
	print(X.shape, Y.shape)
	return (X, Y)

random.seed(42)
random.shuffle(words)
n1 = int(0.8*len(words))
n2 = int(0.9*len(words))

Xtr, Ytr = build_dataset(words[:n1])
Xdev, Ydev = build_dataset(words[n1:n2])
Xte, Yte = build_dataset(words[n2:])


#Better organised

g = torch.Generator().manual_seed(2147483647)
C = torch.randn((27, 10), generator=g)
W1 = torch.randn((30, 200), generator=g)
b1 = torch.randn(200, generator=g)
W2 = torch.randn((200, 27), generator=g)
b2 = torch.randn(27, generator=g)
parameters = [C, W1, b1, W2, b2]

for p in parameters:
	p.requires_grad = True

lre = torch.linspace(-3, 0, 1000) # fluctuation between -0.01 and -1
lrs = 10**lre


#learning rate finder
# lri = []
# lossi_lr = []
# for i in range(1000):
#     ix = torch.randint(0, Xtr.shape[0], (32,), generator=g)
#     emb = C[Xtr[ix]]
#     h = torch.tanh(emb.view(-1, 30) @ W1 + b1)
#     logits = h @ W2 + b2
#     loss = F.cross_entropy(logits, Ytr[ix])
#     for p in parameters:
#         p.grad = None
#     loss.backward()
#     lr = lrs[i]
#     for p in parameters:
#         p.data += -lr * p.grad
#     lri.append(lre[i].item())
#     lossi_lr.append(loss.item())

# plt.plot(lri, lossi_lr)
# plt.show()

lossi = []
stepi = []

for i in range(50000):
	# minibatch construct
	ix = torch.randint(0, Xtr.shape[0], (32,), generator=g)
	# forward pass
	emb = C[Xtr[ix]] # (32, 3, 10)
	h = torch.tanh(emb.view(-1, 30) @ W1 + b1) # (32, 200)
	logits = h @ W2 + b2 # (32, 27)
	loss = F.cross_entropy(logits, Ytr[ix])

	#backward pass
	for p in parameters:
		p.grad = None
	loss.backward()

	#update
	lr = 0.1 if i < 40000 else 0.01 # Determined by the learning rate finder
	for p in parameters:
		p.data += -lr * p.grad

	#trackstats
	stepi.append(i)
	lossi.append(loss.log10().item())

print("dernier minibatch :", loss.item())

# plt.plot(stepi, lossi)
# plt.show()

#Évaluation réelle sur les 3 splits (pas de minibatch, pas de backward)

@torch.no_grad()
def split_loss(X, Y):
	emb = C[X]
	h = torch.tanh(emb.view(-1, 30) @ W1 + b1)
	logits = h @ W2 + b2
	loss = F.cross_entropy(logits, Y)
	return loss.item()

print("train:", split_loss(Xtr, Ytr))
print("dev:  ", split_loss(Xdev, Ydev))
# Xte/Yte : à garder de côté, ne l'utiliser qu'une seule fois tout à la fin du tutoriel

#samples from the model

for _ in range(20):
	out = []
	context = [0] * block_size
	while True:
		emb = C[torch.tensor([context])]
		h = torch.tanh(emb.view(1, -1) @ W1 + b1)
		logits = h @ W2 + b2
		probs = F.softmax(logits, dim=1)
		ix = torch.multinomial(probs, num_samples=1, generator=g).item()
		context = context[1:] + [ix]
		out.append(ix)
		if ix == 0:
			break
	print(''.join(itos[i] for i in out))