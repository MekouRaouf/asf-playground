from app.greetings import bye, greet


def test_greet():
    assert greet("World") == "Hello, World!"


def test_bye():
    assert bye("World") == "Goodbye, World!"
