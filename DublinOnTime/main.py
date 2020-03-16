from enum import Enum, IntEnum
from pydialogflow_fulfillment import DialogflowResponse, DialogflowRequest, SimpleResponse

import falcon
import logging
import json
import pandas as pandas
import requests

logger = logging.getLogger(__name__)
logger.addHandler(logging.StreamHandler())
logger.setLevel(logging.DEBUG)
api = bus_app = falcon.API()
ROUTE = '/busstop'


class APIException(Exception):

    def __init__(self, expression, message):
        self.expression = expression
        self.message = 'I was unable find this information'

class Availability(Enum):
    """Represents the state of the bus availability"""
    ONE_BUS = 1
    MANY_BUSES = 2
    NO_BUSES = 3


class Contants(IntEnum):
    """Limits in this module"""
    MAX_BUSES = 5


class BusStopRequest():
    """Represents a request to this API"""
    def on_post(self, req, resp):
        """Handles POST requests"""
        try:

            json_request = json.load(req.bounded_stream)
            dialogflow_request = DialogflowRequest(json.dumps(json_request))

            if dialogflow_request.get_action() == 'call_busstop_api':
                bus_stop = int(dialogflow_request.get_parameters().get('stop'))
                logger.info("Received request for stop {}".format(bus_stop))
                query_response = self.query_bus_stop(bus_stop)
                bus_times_response_state = self.deserialize_response(query_response)
                api_response = BusStopResponse(bus_times_response_state).response_message
                dialogflow_response = DialogflowResponse()
                dialogflow_response.add(SimpleResponse(api_response, api_response))
                dialogflow_response.expect_user_response = False
                resp.body = dialogflow_response.get_final_response()
                resp.content_type = falcon.MEDIA_JSON
                resp.status = falcon.HTTP_200
            else:
                logger.error("Unknown google action call")
                raise APIException()
        except Exception as error:
            raise APIException
        except APIException:
            raise falcon.HTTP_500

    def get_rtpi_site(self):
        """ Get the actual RTPI site"""
        return 'http://rtpi.ie/Text/WebDisplay.aspx'

    def query_bus_stop(self, stop_number):
        return self.send_request(self.get_rtpi_site() + '?stopRef=' + str(stop_number))

    @staticmethod
    def send_request(full_query):
        """
        Send a request to the RTPI site containing the full site
        and stop we are looking for
        :param full_query: site + query string with bus stop on it
        :return:
        """
        req = requests.get(full_query)
        return req

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
    def __init__(self, bus_response):

        self.bus_response = bus_response
        self.availability = None
        self.prepare_response()
        self.response_message = ''
        self.get_message()

    def get_message(self):
        """Sets the correct message"""

        if self.availability == Availability.MANY_BUSES:
            self.response_message = 'These buses are coming soon. '
        elif self.availability == Availability.ONE_BUS:
            self.response_message = 'One bus is coming. '
        else:
            self.response_message = 'I could not find any buses arriving soon.'
            return
        bus_details_message = ', '.join(self.get_incoming_buses_detailed_message(self.bus_response))
        self.response_message = self.response_message + bus_details_message

    def prepare_response(self):
        try:
            if self.bus_response.Service.size > 1:
                self.availability = Availability.MANY_BUSES
                if self.bus_response.Service.size > Contants.MAX_BUSES:
                    self.bus_response = self.bus_response.head(Contants.MAX_BUSES)
            elif self.bus_response.Service.size == 1:
                self.availability = Availability.ONE_BUS
            else:
                self.availability = Availability.NO_BUSES
        except Exception as error:
            self.availability = Availability.NO_BUSES

    @staticmethod
    def get_incoming_buses_detailed_message(bus_response):

        message = ''

        def isTime(time_value):
            """
            Check if the reply had a time-like value such as 22:05
            """
            return ":" in str(time_value)

        def isDue(time_value):
            """
            check if we value is 'due'
            """
            return str(time_value).lower() == 'due'

        def prepare_message(service_time):
            """
            Prepare a user-friendly message
            """
            message = service_time[0] + ' '
            if isDue(service_time[1]):
                message += ' is due'
            elif isTime(service_time[1]):
                # 22:05 changes to '22 05'
                message += ' is coming at ' + service_time[1].replace(':', ' ')
            else:
                message += service_time[1].replace('Mins', 'minutes')
            return message

        r = bus_response
        service_time_message = [prepare_message((service, time)) for service, time in zip(r['Service'], r['Time'])]
        return service_time_message


bus_app.add_route(ROUTE, BusStopRequest())

