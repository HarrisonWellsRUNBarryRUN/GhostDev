"""
Sample application module containing basic mathematical operations.
"""

def divide_numbers(a: float, b: float):
    """
    Divides number a by number b.
    Should handle division by zero safely by returning None.
    """
    try:
        val_a = float(a)
        val_b = float(b)
        if val_b == 0.0:
            return None
        return val_a / val_b
    except (ZeroDivisionError, OverflowError, TypeError, ValueError):
        return None

def add_numbers(a: float, b: float) -> float:
    """Returns the sum of a and b."""
    return a + b
