"""
Sample application module containing basic mathematical operations.
"""

def divide_numbers(a: float, b: float):
    """
    Divides number a by number b.
    Should handle division by zero safely by returning None.
    """
    if b == 0:
        return None
    return a / b

def add_numbers(a: float, b: float) -> float:
    """Returns the sum of a and b."""
    return a + b
