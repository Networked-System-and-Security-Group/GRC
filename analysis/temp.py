a, b = 0.5, 0.5
m, n = 1.2, 1.1
for i in range(10):
    a = a * m
    b = b * n
    a, b = a/(a+b), b/(a+b)
    print(f'{a:.3f}, {b:.3f}')