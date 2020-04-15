""" Allows people in Dublin to ask the Google assistant when their bus is coming to a particular bus stop.

This module provides a web service using the falcon framework which receives and responds to requests from
Google's Dialogflow. The actual information is obtained by doing some good old scrapin' of the RTPI.ie site

Ireland, March 2020.
"""

import json
import logging
import random
import re
from enum import Enum, IntEnum

from falcon import API, MEDIA_JSON, HTTP_200
import pandas
import requests
from pydialogflow_fulfillment import DialogflowResponse, DialogflowRequest, SimpleResponse

LOGGER = logging.getLogger(__name__)
LOGGER.addHandler(logging.StreamHandler())
LOGGER.setLevel(logging.DEBUG)
BUS_SERVICE_API = BUS_APP = API()
BUS_STOP_ROUTE = '/busstop'


class APIException(Exception):
    """ Generic Exception for this API"""


class Availability(Enum):
    """Represents the state of the bus availability"""
    ONE_BUS = 1
    MANY_BUSES = 2
    NO_BUSES = 3


class Constants(IntEnum):
    """Limits in this module"""
    MAX_BUSES = 5


class BusStopRequest():
    """Represents a request to this API"""

    def on_post(self, req, resp):
        """Handles POST requests"""
        try:
            LOGGER.info('new request received')
            json_request = json.load(req.bounded_stream)
            dlg_flow_req = DialogflowRequest(json.dumps(json_request))
            stop_param = '' if 'stop' not in dlg_flow_req.get_parameters() \
                else dlg_flow_req.get_parameters().get('stop')
            match_numbers = re.findall('\d+', stop_param)
            if dlg_flow_req.get_action() == 'call_busstop_api' and stop_param and match_numbers:
                LOGGER.info('stop parameter is {}'.format(stop_param))
                if ' to ' in stop_param:
                    # This converts '70 to 94' to '7294'
                    index = stop_param.index(' to ')
                    stop_param = stop_param[:index - 1] + '2' + stop_param[index + 4:]
                else:
                    stop_param = match_numbers[0]  # This will grab the digits in the string
                stop_param = stop_param.replace(' ', '')  # ensure we don't have spaces
                bus_stop = int(stop_param.split('.', 1)[0])
                LOGGER.info("Resolved bus stop: {}".format(bus_stop))
                query_response = self.query_bus_stop(bus_stop)
                bus_times_response_state = self.deserialize_response(query_response)
                response = BusStopResponse(bus_times_response_state)
                response_message = response.response_message
                final_response = response_message + BusStopResponse.get_goodbye_message()
                LOGGER.info('Setting response to {}'.format(final_response))
                resp.body = response.create_google_response(final_response)
                resp.content_type = MEDIA_JSON
                resp.status = HTTP_200
            elif dlg_flow_req.get_action() == 'call_busstop_api':
                LOGGER.info('bus stop request did no contain valid stop parameter')
                resp.body = self.create_google_response(
                    BusStopResponse.get_greeting_with_question(), True)
                resp.content_type = MEDIA_JSON
                resp.status = HTTP_200
            else:
                raise APIException()
        except Exception as error:
            LOGGER.error('There was an error processing this request')
            LOGGER.error(str(error))
            resp.body = self.create_google_response(BusStopResponse.get_error_message())
            resp.content_type = MEDIA_JSON
            resp.status = HTTP_200

    def query_bus_stop(self, stop_number):
        """ Build full query string to send to RTPI site"""
        return self.send_request(self.get_rtpi_site() + '?stopRef=' + str(stop_number))


    @staticmethod
    def get_rtpi_site():
        """ Get the actual RTPI site"""
        return 'http://rtpi.ie/Text/WebDisplay.aspx'

    @staticmethod
    def send_request(full_query):
        """
        Send a request to the RTPI site containing the full site
        and stop we are looking for
        :param full_query: site + query string with bus stop on it
        :return:
        """
        return requests.get(full_query)

    @staticmethod
    def deserialize_response(raw_response):
        """
        Parse the response into a Pandas dataframe
        """
        body = raw_response.content.decode('utf-8')
        tables = pandas.read_html(body)  # Returns list of all tables on page
        html_table = tables[0]  # Grab the first table we are interested in
        service_times = html_table[['Service', 'Time']]
        return service_times


class BusStopResponse():
    """
    Represents a response to the client from this API
    """
    greetings = ['Welcome to Dublin on time. Please tell me the '
                 'bus stop number you would like me to check for you',
                 'Hello!, please tell me the stop number you would like me to verify',
                 'Hey there, please tell me the stop number you need me to check',
                 'Hi, please tell me the stop number']

    error_messages = ['Sorry, I could not find this information. Please try later.',
                      'It was not possible to get this information. Please try again later',]

    single_bus_message = ['One bus is coming.', 'There is one bus coming  ']

    many_buses_message = [' These buses are coming soon: ', ' The following buses are coming:  ',
                          ' These are the buses coming to your bus stop: ']
    goodbye_message = [' Have a safe trip!', ' Goodbye!', ' Have a nice day!', ' Have a great day!', '  Adios!']

    def __init__(self, bus_response):

        self.bus_response = bus_response
        self.availability = None
        self.response_message = ''
        self.set_availability()
        self.set_message()

    @staticmethod
    def make_ssml_message(message):
        return '<speak>' + message + '</speak>'

    def create_google_response(self, message, expect_user_response=False):
        """ Build the dialogflow response in the correct format"""

        google_response = DialogflowResponse()
        google_response.expect_user_response = expect_user_response
        google_response.add(SimpleResponse(self.get_text_only_message(message),
                                               self.make_ssml_message(message)))
        return google_response.get_final_response()

    @classmethod
    def get_greeting_with_question(cls):
        """ To be sent as an initial greeting when app is launch with parameters"""
        return random.choice(cls.greetings)

    @staticmethod
    def get_text_only_message(message):
        return re.sub('<[^>]+>', '', message)

    @classmethod
    def get_error_message(cls):
        """ To be sent if something went wrong"""
        return random.choice(cls.error_messages)

    @classmethod
    def get_single_bus_message_initial_greeting(cls):
        """ initial greeting to a single bus prior to replying"""
        return cls.make_paragraph(random.choice(cls.single_bus_message))

    @classmethod
    def get_goodbye_message(cls):
        """ message to be appended to a final positive response"""
        return cls.add_speech_pause(random.choice(cls.goodbye_message), 'before', '2s' )

    @classmethod
    def get_many_buses_initial_greeting(cls):
        """ initial greeting for multiple buses prior to replying"""
        return cls.make_paragraph(random.choice(cls.many_buses_message))

    @staticmethod
    def make_paragraph(message):
        return '<p><s>' + message + '</s></p>'

    @staticmethod
    def add_speech_pause(message, when, time):
        # use SSML syntax to define time, i.e 1s or 500ms
        # when: before or after
        if when == 'before':
            return '<break time=\"' + time + '\"/>' + message
        elif when == 'after':
            return message + '<break time=\"' + time + '\"/>'
        return message

    def set_message(self):
        """Sets the correct message"""

        if self.availability == Availability.MANY_BUSES:
            self.response_message = self.get_many_buses_initial_greeting()
        elif self.availability == Availability.ONE_BUS:
            self.response_message = self.get_single_bus_message_initial_greeting()
        else:
            self.response_message = 'I could not find any buses arriving at this bus stop.'

        if self.availability == Availability.MANY_BUSES or self.availability == Availability.ONE_BUS:
            LOGGER.info('Buses are available. Building message')
            bus_details_message = ', '.join(self.get_incoming_buses_detailed_message(self.bus_response))
            self.response_message = self.response_message + bus_details_message

    def set_availability(self):
        """ Set the type of bus availability based on response from RTPI """
        try:
            if self.bus_response.Service.size > 1:
                self.availability = Availability.MANY_BUSES
                if self.bus_response.Service.size > Constants.MAX_BUSES:
                    self.bus_response = self.bus_response.head(Constants.MAX_BUSES)
            elif self.bus_response.Service.size == 1:
                self.availability = Availability.ONE_BUS
            else:
                self.availability = Availability.NO_BUSES
        except Exception:
            self.availability = Availability.NO_BUSES

    @staticmethod
    def get_incoming_buses_detailed_message(bus_response):
        """ Gets a user friendly message with bus service information"""

        def is_time(time_value):
            """
            Check if the reply had a time-like value such as 22:05
            """
            return ":" in str(time_value)

        def is_due(time_value):
            """
            check if we value is 'due'
            """
            return str(time_value).lower() == 'due'

        def prepare_message(service_time):
            """
            Prepare a user-friendly message
            """
            message = str(service_time[0]) + ' '
            if is_due(service_time[1]):
                message += ' is due'
            elif is_time(service_time[1]):
                # 22:05 changes to '22 05'
                message += ' is coming at <say-as interpret-as="time" format="24"> ' +\
                           service_time[1] + '</say-as>'
            else:
                message += service_time[1].replace('Mins', 'minutes')
            return message

        resp = bus_response
        service_time_message = [prepare_message((service, time))
                                for service, time in zip(resp['Service'], resp['Time'])]
        return service_time_message


BUS_APP.add_route(BUS_STOP_ROUTE, BusStopRequest())
