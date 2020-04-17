""" Allows people in Dublin to ask the Google assistant when their bus is coming to a particular bus stop.

This module provides a web service using the falcon framework which receives and responds to requests from
Google's Dialogflow. The actual information is obtained by doing some good old scrapin' of the RTPI.ie site

Ireland, March 2020.
"""

import json
import logging
import re
from enum import Enum, IntEnum

import messages as msgs
import pandas
import requests
from falcon import API, MEDIA_JSON, HTTP_200
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
            google_request = DialogflowRequest(json.dumps(json_request))
            bus_stop = self.get_bus_stop(google_request)
            if bus_stop:
                LOGGER.info("Resolved bus stop: {}".format(bus_stop))
                query_response = self.query_bus_stop(bus_stop)
                bus_times_response_state = self.deserialize_response(query_response)
                resp.body = BusStopResponse(bus_times_response_state).provide_good_response()
                resp.content_type = MEDIA_JSON
                resp.status = HTTP_200
            elif google_request.get_action() == 'call_busstop_api':
                LOGGER.info('bus stop request did no contain valid stop parameter')
                resp.body = BusStopResponse().request_stop_response()
                resp.content_type = MEDIA_JSON
                resp.status = HTTP_200
            else:
                raise APIException()
        except Exception as error:
            LOGGER.error('There was an error processing this request')
            LOGGER.error(str(error))
            resp.body = BusStopResponse().provide_error_response()
            resp.content_type = MEDIA_JSON
            resp.status = HTTP_200

    def query_bus_stop(self, stop_number):
        """ Build full query string to send to RTPI site"""
        return self.send_request(self.get_rtpi_site() + '?stopRef=' + str(stop_number))

    @staticmethod
    def get_bus_stop(google_request):
        bus_stop = None
        stop_param = '' if 'stop' not in google_request.get_parameters() else \
            google_request.get_parameters().get('stop')
        if not stop_param:
            return None
        stop_param = stop_param.replace('/', '')  # convert 24/72 to 2472
        match_numbers = re.findall('\d+', stop_param)
        if google_request.get_action() == 'call_busstop_api' and stop_param and match_numbers:
            LOGGER.info('stop parameter is {}'.format(stop_param))
        if ' to ' in stop_param:
            # This converts '70 to 94' to '7294'
            index = stop_param.index(' to ')
            stop_param = stop_param[:index - 1] + '2' + stop_param[index + 4:]
        else:
            stop_param = match_numbers[0]  # This will grab the digits in the string
        stop_param = stop_param.replace(' ', '')  # ensure we don't have spaces
        bus_stop = int(stop_param.split('.', 1)[0])
        return bus_stop

    @staticmethod
    def get_rtpi_site():
        """ Get the actual RTPI site"""
        return 'http://rtpi.ie/Text/WebDisplay.aspx'

    @staticmethod
    def send_request(full_query):
        """
        Send a request to the RTPI site containing the full site
        and stop we are looking for
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
    def __init__(self, bus_response=None):

        self.bus_response = bus_response
        self.availability = None
        self.response_message = ''
        self.set_availability()
        self.set_message()

    def request_stop_response(self):
        return self.create_google_response(msgs.get_greeting_with_question(), True)

    def provide_error_response(self):
        return self.create_google_response(msgs.get_error_message() + msgs.get_goodbye_message())

    def provide_good_response(self):
        final_response = self.response_message + msgs.get_goodbye_message()
        LOGGER.info('Setting response to  \n {}'.format(final_response))
        return self.create_google_response(final_response)

    def create_google_response(self, message, expect_user_response=False):
        """ Build the dialogflow response in the correct format"""

        google_response = DialogflowResponse()
        google_response.expect_user_response = expect_user_response
        google_response.add(SimpleResponse(message, msgs.text_to_ssml(message)))
        return google_response.get_final_response()

    def set_message(self):
        """Sets the correct message"""

        if self.availability == Availability.MANY_BUSES:
            self.response_message = msgs.get_many_buses_initial_greeting()
        elif self.availability == Availability.ONE_BUS:
            self.response_message = msgs.get_single_bus_message_initial_greeting()
        else:
            self.response_message = msgs.get_random_message('no_buses')

        if self.availability == Availability.MANY_BUSES or self.availability == Availability.ONE_BUS:
            LOGGER.info('Buses are available. Building message')
            bus_details_message = '\n '.join(self.get_incoming_buses_message(self.bus_response))
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
    def get_incoming_buses_message(bus_response):
        """ Gets a user friendly message with bus service information from source system"""

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
                message += ' is coming at ' + service_time[1]
            else:
                message += service_time[1].replace('Mins', 'minutes')
            return message

        resp = bus_response
        service_time_message = [prepare_message((service, time))
                                for service, time in zip(resp['Service'], resp['Time'])]
        return service_time_message


BUS_APP.add_route(BUS_STOP_ROUTE, BusStopRequest())
