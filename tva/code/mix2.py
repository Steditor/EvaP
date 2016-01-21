def mix2(a, b):
    if a == 0 and b == 0:
        return 1
    if a == 2:
        return 2
    if b == 3:
        return 3

    return 4

def expected_result_set():
    return [1, 2, 3, 4]
