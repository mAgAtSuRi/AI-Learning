import torch
import matplotlib.pyplot as plt
words = open('names.txt').read().splitlines()

# Store combinaison in a 2d array
N = torch.zeros((27, 27), dtype=torch.int32)
# print(N)

# list of all the characters used in the names 
chars = sorted(list(set(''.join(words))))
# Map them with numbers
stoi = {s: i+1 for i, s in enumerate(chars)}
stoi['.'] = 0
itos = {i: s for s, i in stoi.items()}

for w in words:
	chs = ['.'] + list(w) + ['.']
	for ch1, ch2 in zip(chs, chs[1:]):
		ix1 = stoi[ch1]
		ix2 = stoi[ch2]
		N[ix1, ix2] += 1

plt.figure(figsize=(16,16))
plt.imshow(N, cmap='Blues')
for i in range(27):
	for j in range(27):
		chstr = itos[i] + itos[j]
		plt.text(j, i , chstr, ha="center", va="bottom", color='gray')
		plt.text(j, i , N[i, j].item(), ha="center", va="top", color='gray')
plt.axis('off')
# plt.show()

P = N.float()
P = P / P.sum(1, keepdim=True)
g = torch.Generator().manual_seed(2147483647)

for i in range(5):
	out = []
	ix = 0
	while True:
		p = P[ix]
		# p = N[ix].float()
		# p = p / p.sum()
		ix = torch.multinomial(p, num_samples=1, replacement=True, generator=g).item()
		out.append(itos[ix])
		if ix == 0:
			break
	print(''.join(out))