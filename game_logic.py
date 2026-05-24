def validate_number(number: str) -> tuple[bool, str]:
    number = number.strip()
    if not number:
        return False, "Введите число: нужно ровно 4 разные цифры"
    if len(number) != 4:
        return False, "Число должно содержать ровно 4 цифры"
    if not number.isdigit():
        return False, "Допустимы только цифры"
    if len(set(number)) != 4:
        return False, "Цифры не должны повторяться"
    return True, ""

def calculate_bulls_and_cows(secret: str, guess: str) -> tuple[int, int]:
    bulls = 0
    cows = 0
    for i in range(4):
        if guess[i] == secret[i]:
            bulls += 1
        elif guess[i] in secret:
            cows += 1
    return bulls, cows

def format_result(attempt: str, bulls: int, cows: int) -> str:
    bull_word = _plural_ru(bulls, "бык", "быка", "быков")
    cow_word = _plural_ru(cows, "корова", "коровы", "коров")
    return f"{attempt} -> {bulls} {bull_word}, {cows} {cow_word}"

def _plural_ru(n: int, form1: str, form2: str, form5: str) -> str:
    if 11 <= n % 100 <= 19:
        return form5
    rem = n % 10
    if rem == 1:
        return form1
    if 2 <= rem <= 4:
        return form2
    return form5