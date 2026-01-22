def main():
	l = [52633, 8137, 1024, 999]

	for num in l:
		print_factor(num)	

def print_factor(x):
	factors = []

	for i in range(2, x//2): # I'm using //2 because no factor will be larger than half of x
		if not (x % i): # in python anything other than 0 is true
			factors.append(i)

	print("Factors of ", x, ": ", factors, sep='') if factors else print(x, "is prime.")
    
if __name__ == '__main__':
	main()
