from graphviz import Digraph
import math
import torch
import random

class Value:
	def __init__(self, data, _children=(), _op='', label = ''):
		self.data = data
		self.grad = 0.0
		self._backward = lambda: None
		self._prev = set(_children)
		self._op = _op
		self.label = label

	def __repr__(self):
		return f"Value(data={self.data})"

	def __add__(self, other):
		other = other if isinstance(other, Value) else Value(other)
		out = Value(self.data + other.data, (self, other), '+')

		def _backward():
			self.grad += 1.0 * out.grad
			other.grad += 1.0 * out.grad
		out._backward = _backward
		return out
	
	def __sub__(self, other):
		return self + (-other)

	def __mul__(self, other):
		other = other if isinstance(other, Value) else Value(other)
		out = Value(self.data * other.data, (self, other), '*')

		def _backward():
			self.grad += other.data * out.grad
			other.grad += self.data * out.grad
		out._backward = _backward
		return out
	
	def __rmul__(self, other):
		return self * other

	def __pow__(self, other):
		assert isinstance(other, (int, float))
		out = Value(self.data ** other, (self, ), f'**{other}')

		def _backward():
			self.grad = other * (self.data ** (other - 1)) * out.grad
		out._backward = _backward
		return out

	def __truediv__(self, other):
		return self * other ** -1

	def tanh(self):
		x = self.data
		t = (math.exp(2*x) - 1) / (math.exp(2*x) + 1)
		out = Value(t, (self,), 'tanh')

		def _backward():
			self.grad += (1 - t**2) * out.grad
		out._backward = _backward
		return out

	def exp(self):
		x =self.data
		out = Value(math.exp(x), (self, ), 'exp')

		def _backward():
			self.grad += out.data * out.grad
		out._backward = _backward
		return out

	def backward(self):
		topo = []
		visited = set()
		def build_topo(v):
			if v not in visited:
				visited.add(v)
				for child in v._prev:
					build_topo(child)
				topo.append(v)

		build_topo(self)
		self.grad = 1.0
		for node in reversed(topo):
			node._backward()

a = Value(2.0, label='a')
b = Value(-3.0, label='b')
c = Value(10.0, label='c')
e = a * b; e.label = 'e'
d = e + c; d.label = 'd'
f = Value(-2.0, label='f')
L = d * f; L.label = 'L'

def trace(root):
	nodes, edges = set(), set()
	def build(v):
		if v not in nodes:
			nodes.add(v)
			for child in v._prev:
				edges.add((child, v))
				build(child)
	build(root)
	return nodes, edges

def draw_dot(root):
	dot = Digraph(format='svg', graph_attr={'rankdir': 'LR'})

	nodes, edges = trace(root)
	for n in nodes:
		uid = str(id(n))
		dot.node(name=uid, label="{ %s | data %.4f | grad %.4f }" % (n.label, n.data, n.grad), shape='record')
		if n._op:
			dot.node(name=uid + n._op, label=n._op, shape='box')
			dot.edge(uid + n._op, uid)
	for n1, n2 in edges:
		dot.edge(str(id(n1)), str(id(n2)) + n2._op)
	
	return dot

# 	draw first graph
# draw_dot(L).render('graph', format='svg')

# x1 = Value(2.0, label='x1')
# x2 = Value(0.0, label='x2')
# w1 = Value(-3.0, label='w1')
# w2 = Value(1.0, label='w2')
# b = Value(6.8813735870195432, label='b')
# x1w1 = x1 * w1; x1w1.label = 'x1w1'
# x2w2 = x2 * w2; x2w2.label = 'x2w2'
# x1w1x2w2 = x1w1 + x2w2; x1w1x2w2.label = 'x1w1x2w2'
# n = x1w1x2w2 + b; n.label = 'n'
# o = n.tanh(); o.label = 'o'
# Other expression of o
# e = (2 * n).exp()
# o = (e - 1) / (e + 1)
# # Automatically 
# o.backward()

# Semi Automatically
# o.grad = 1.0
# o._backward()
# n._backward()
# b._backward()
# x1w1x2w2._backward()
# x1w1._backward()
# x2w2._backward()
# Manually
# x1w1x2w2.grad = 0.5
# x1w1.grad =0.5
# x2w2.grad = 0.5
# x1.grad = w1.data * x1w1.grad
# w1.grad = x1.data * x1w1.grad
# x2.grad = w2.data * x2w2.grad
# w2.grad = x2.data * x2w2.grad
# b.grad = 0.5
# n.grad = 0.5
# o.grad = 1.0

# draw_dot(o).render('graph', format='svg')

# Tensor
# x1 = torch.tensor([2.0], dtype=torch.double, requires_grad=True)
# x2 = torch.tensor([0.0], dtype=torch.double, requires_grad=True)

# w1 = torch.tensor([-3.0], dtype=torch.double, requires_grad=True)
# w2 = torch.tensor([1.0], dtype=torch.double, requires_grad=True)
# b = torch.tensor([6.8813735870195432], dtype=torch.double, requires_grad=True)
# n = x1 * w1 +x2 *w2 + b
# o = torch.tanh(n)
# print(o.data.item())
# o.backward()
# print('---')
# print('x1', x1.grad.item())
# print('w1', w1.grad.item())
# print('x2', x2.grad.item())
# print('w2', w2.grad.item())

class Neuron:
	def __init__(self, nin):
		self.w = [Value(random.uniform(-1, 1)) for _ in range(nin)]
		self.b = Value(random.uniform(-1, 1))
	
	def __call__(self, x):
		act = sum((wi * xi for wi, xi in zip(self.w, x)), self.b)
		out = act.tanh()
		return out

	def parameters(self):
		return self.w + [self.b]

class Layer:
	def __init__(self, nin, nout):
		self.neurons = [Neuron(nin) for _ in range(nout)]

	def __call__(self, x):
		outs = [n(x) for n in self.neurons]
		return outs[0] if len(outs) == 1 else outs

	def parameters(self):
		return [p for neuron in self.neurons for p in neuron.parameters]
class MLP:
	def __init__(self, nin, nouts):
		sz = [nin] + nouts
		self.layers = [Layer(sz[i], sz[i + 1]) for i in range(len(nouts))]
	
	def __call__(self, x):
		for layer in self.layers:
			x = layer(x)
		return x

	def parameters(self):
		return [p for layer in self.layers for p in layer.parameters]

# Single neuron
# x = [2.0, 3.0]
# n = Neuron(2)
# print(n(x))

#Layer of 3 neurons
# x = [2.0, 3.0]
# n = Layer(2, 3)
# print(n(x))

# Réseau de neurones 3 4 4 1
x = [2.0, 3.0, -1]
n = MLP(3, [4, 4, 1])
# print(n(x))
# draw_dot(n(x)).render('graph', format='svg')

# print(n.parameters())

# dataset
xs = [
	[2.0, 3.0, -1.0],
	[3.0, -1.0, 0.5],
	[0.5, 1.0, 1.0],
	[1.0, 1.0, -1.0],
]
ys = [1.0, -1.0, -1.0, 1.0] #desired targets
# ypred = [n(x) for x in xs]
# print(ypred)

# Loss 
# loss = sum((yout - ygt)**2 for yout, ygt in zip(ypred, ys))
# print(loss)

# Training Neural Network 

# forward pass
for k in range(10):
	ypred = [n(x) for x in xs]
	loss = sum((yout - ygt)**2 for ygt, yout in zip(ys, ypred))

	# backward pass
	for p in n.parameters:
		p.grad = 0.0
	loss.backward()

	# update 
	for p in n.parameters():
		p.data += -0.05 * p.grad
	
	print(k, loss.data)