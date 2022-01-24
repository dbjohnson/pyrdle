import os
import time
import json
import re
import random
from collections import defaultdict

import requests
from webdriver_manager.chrome import ChromeDriverManager
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def load_words():
    """
    extract valid word list from javascript src
    """
    script_text = requests.get(
        "https://www.powerlanguage.co.uk/wordle/main.e65ce0a5.js"
    ).text
    return {
        word
        # minified variable names, in effect:
        # La = possible solution words
        # Ta = other legal words
        # (some words are not easily searchable in a few guesses because of
        #  many near neighbors; wordle source lists them separately.
        #  We will include all legal in our search space)
        for var in ('La', 'Ta')
        for word in json.loads(
            re.search(
                fr'\b{var}=(.*?])',
                script_text
            ).groups()[0]
        )
    }


def solve(randomize_first_guess=False):
    # get legal word list
    words = load_words()
    letter_counts = defaultdict(int)
    for word in words:
        for letter in word:
            letter_counts[letter] += 1

    # suppress webdriver log chatter :|
    os.environ['WDM_LOG_LEVEL'] = '0'
    # initialize webdriver and load page
    wd = webdriver.Chrome(
        service=Service(ChromeDriverManager().install())
    )
    wd.get('https://www.powerlanguage.co.uk/wordle/')

    # get references to board, keyboard, and modal  elements
    def expand_shadow_root(parent):
        return wd.execute_script(
            "return arguments[0].shadowRoot",
            parent
        )

    game = expand_shadow_root(
        wd.find_element(By.CSS_SELECTOR, 'game-app'),
    ).find_element(
        By.CSS_SELECTOR, 'game-theme-manager'
    ).find_element(
        By.ID, 'game'
    )
    board = game.find_element(By.XPATH, '*/div[@id="board"]')
    modal = game.find_element(By.CSS_SELECTOR, 'game-modal')
    keyboard = expand_shadow_root(
        game.find_element(By.CSS_SELECTOR, 'game-keyboard'),
    ).find_element(
        By.CSS_SELECTOR, 'div'
    )

    # close instructions modal
    WebDriverWait(wd, 3).until(
        EC.element_to_be_clickable(game)
    ).click()

    def enter_guess(word):
        """
        Enter guess by clicking virtual keyboard buttons
        """
        for letter in word.lower() + '↵':
            keyboard.find_element(
                By.XPATH,
                f'*/button[@data-key="{letter}"]'
            ).click()

    def read_board():
        """
        Read previous guesses plus grades
        """
        for row in board.find_elements(By.CSS_SELECTOR, 'game-row'):
            row = expand_shadow_root(row).find_element(By.CSS_SELECTOR, 'div')
            tiles = row.find_elements(By.CSS_SELECTOR, 'game-tile')
            letters = list(filter(
                None,
                [t.get_dom_attribute('letter') for t in tiles]
            ))
            grades = list(filter(
                None,
                [t.get_dom_attribute('evaluation') for t in tiles]
            ))
            if letters:
                yield letters, grades

    def get_candidates():
        """
        filter down word list to candidates that fit constraints from
        previous guesses
        """
        candidates = words.copy()
        for guess, grades in read_board():
            for i, (l, g) in enumerate(zip(guess, grades)):
                try:
                    candidates.remove(''.join(guess))
                except KeyError:
                    pass

                if g == 'absent':
                    # if "absent" check for special case where the letter
                    # is in the guess more than once
                    if all([
                        g2 == 'absent'
                        for l2, g2 in zip(guess, grades)
                        if l2 == l
                    ]):
                        candidates = {
                            c for c in candidates
                            if l not in c
                        }
                    else:
                        candidates = {
                            c for c in candidates
                            if c[i] != l
                        }
                elif g == 'present':
                    candidates = {
                        c for c in candidates
                        if l in c and c[i] != l
                    }
                elif g == 'correct':
                    candidates = {
                        c for c in candidates
                        if c[i] == l
                    }

        return candidates

    def best_guess(candidates, try_num):
        """
        optimize for maximum filtering for the first few guesses
        (penalize repeated letters), but then just try to get the best overall
        score (total letter frequency) as time runs out
        """
        return max(
            sorted(candidates),
            key=lambda word:
            sum(
                letter_counts[letter]
                for letter in (set(word) if try_num < 4 else word)
            )
        )

    # try to solve the puzzle!
    if randomize_first_guess:
        enter_guess(random.choice(list(words)))
    else:
        enter_guess(best_guess(words, 0))

    # keep trying the next best guess until the modal pops up to tell
    # us we're done
    try_num = 1
    while not modal.get_dom_attribute('open'):
        candidates = get_candidates()
        if candidates:
            time.sleep(1)
            enter_guess(best_guess(candidates, try_num))
            try_num += 1

    # see if we solved the puzzle
    guesses = list(read_board())
    last_guess, grade = guesses[-1]
    solved = set(grade) == {'correct'}
    if solved:
        print(f'solution "{"".join(last_guess)}" found in {len(guesses)} guesses!')
    else:
        print('Wah wah!')

    print(f'WordleBot {len(guesses)}/6')
    print('\n'.join([
        ''.join([{
            'absent': '⬛',
            'present': '🟨',
            'correct': '🟩'
        }[g]
            for g in grade
        ])
        for guess, grade in guesses
    ]))
    wd.close()
    return solved


if __name__ == '__main__':
    solve(True)
