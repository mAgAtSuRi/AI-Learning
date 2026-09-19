import torch
import torch.nn.functional as F

words = open('names.txt').read().splitlines()

# map each letter woth corresponding index
chars = sorted(list((set(''.join(words)))))
stoi = {s: i+1 for i, s in enumerate(chars)}
stoi['.'] = 0
itos = {i: s for s, i in stoi.items()}

# create datset
xs1,xs2, ys = [], [], []
for w in words:
	# add '.' at the beginning and end of each words
	chs = ['.', '.'] + list(w) + ['.']

	# Store all the letter indexes in xs and ys
	for ch1, ch2, ch3 in zip(chs, chs[1:], chs[2:]):
		ix1 = stoi[ch1]
		ix2 = stoi[ch2]
		ix3 = stoi[ch3]
		xs1.append(ix1)
		xs2.append(ix2)
		ys.append(ix3)
xs1 = torch.tensor(xs1)
xs2 = torch.tensor(xs2)
ys = torch.tensor(ys)
num = xs1.nelement()
print('number of examples: ', num)

#initialize network
g = torch.Generator().manual_seed(2147483647)
W = torch.randn(54, 27, generator=g, requires_grad=True)

# Gradient descent
for k in range(100):

	# Forward pass
	xenc1 = F.one_hot(xs1, num_classes=27).float()
	xenc2 = F.one_hot(xs2, num_classes=27).float()
	xenc = torch.cat([xenc1, xenc2], dim=1)
	logits = xenc @ W
	counts = logits.exp()
	probs = counts / counts.sum(1, keepdim=True)
	loss = -probs[torch.arange(num), ys].log().mean()
	# print(loss.item())

	# Backward pass
	W.grad = None
	loss.backward()

	# Update
	W.data += -10 * W.grad
print(loss.item())

for i in range(5):
	out = []
	ix1, ix2 = 0, 0

	while True:
		xenc1 = F.one_hot(torch.tensor([ix1]), num_classes=27).float()
		xenc2 = F.one_hot(torch.tensor([ix2]), num_classes=27).float()
		xenc = torch.cat([xenc1, xenc2], dim=1)
		logits = xenc @ W
		counts = logits.exp() # equivalent N
		p = counts / counts.sum(1, keepdim=True)

		ix3 = torch.multinomial(p, num_samples=1, replacement=True, generator=g).item()
		out.append(itos[ix3])

		if ix3 == 0:
			break
		ix1, ix2 = ix2, ix3
	print(''.join(out))