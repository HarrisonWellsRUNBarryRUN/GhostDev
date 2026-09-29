import pytest
from sample_app import divide_numbers, add_numbers

def test_add_numbers():
    assert add_numbers(2, 3) == 5

def test_divide_numbers_valid():
    assert divide_numbers(10, 2) == 5.0

def test_divide_numbers_zero():
    # Expected behavior: return None instead of raising ZeroDivisionError
    assert divide_numbers(10, 0) is None

def test_divide_numbers_negative():
    assert divide_numbers(-6, 2) == -3.0
