def mix(a, b, alpha):
  if a is None and b is None:
    return None
  if a is None:
    return b
  if b is None:
    return a

  return alpha * a + (1 - alpha) * b
