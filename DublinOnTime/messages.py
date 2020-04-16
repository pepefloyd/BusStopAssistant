import pathlib
import random
import re

import yaml


def get_random_message(message_type):
    msg_file = pathlib.Path(__file__).parent.parent / 'resources/messages.yaml'
    with open(msg_file) as file:
        messages = yaml.load(file, Loader=yaml.FullLoader)
        return random.choice(messages[message_type])


def convert_times(text):
    pre_time_ssml = '<say-as interpret-as="time" format="24">'
    post_time_ssml = '</say-as>'
    regex = '(\d{1,2}[:]\d{1,2})'
    return re.sub(regex, lambda m: pre_time_ssml + m.group(0) + post_time_ssml, text)


def text_to_ssml(text):
    # Convert plaintext to SSML
    # Add a 2 second pause for every newline
    ssml = '<speak>{}</speak>'.format(text.replace('\n', '\n<break time="1s"/>'))
    ssml = convert_times(ssml)
    return ssml


def get_greeting_with_question():
    """ To be sent as an initial greeting when app is launch with parameters"""
    return get_random_message('greetings')


def get_no_buses_message():
    return get_random_message('no_buses')


def get_error_message():
    """ To be sent if something went wrong"""
    return get_random_message('errors')


def get_single_bus_message_initial_greeting():
    """ initial greeting to a single bus prior to replying"""
    return get_random_message('single_bus')


def get_goodbye_message():
    """ message to be appended to a final positive response"""
    return get_random_message('farewells')


def get_many_buses_initial_greeting():
    """ initial greeting for multiple buses prior to replying"""
    return get_random_message('many_buses')
