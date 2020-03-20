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
    pass


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
            logger.info('Received a new request')
            json_request = json.load(req.bounded_stream)
            dlg_flow_req = DialogflowRequest(json.dumps(json_request))
            stop_param = dlg_flow_req.get_parameters().get('stop') if 'stop' in dlg_flow_req.get_parameters() else ''
            logger.info('stop parameter is {}'.format(stop_param))
            if dlg_flow_req.get_action() == 'call_busstop_api' and len(stop_param) > 0:
                bus_stop = int(stop_param)
                logger.info("Received request for stop {}".format(bus_stop))
                query_response = self.query_bus_stop(bus_stop)
                bus_times_response_state = self.deserialize_response(query_response)
                api_response = BusStopResponse(bus_times_response_state).response_message
                logger.info('Setting response to {}'.format(api_response))
                resp.body = self.create_dialogflow_response(api_response)
                resp.content_type = falcon.MEDIA_JSON
                resp.status = falcon.HTTP_200
            else:
                logger.error("Unknown request. Request {}".format(str(json.load(req.bounded_stream))))
                raise APIException()
        except Exception as error:
            logger.error(str(error))
            resp.body = self.create_dialogflow_response("Sorry, I could not find this information."
                                                        " Can you try again?", True)
            resp.content_type = falcon.MEDIA_JSON
            resp.status = falcon.HTTP_200

    def create_dialogflow_response(self, response, expect_user_response= False):

        dialogflow_response = DialogflowResponse()
        dialogflow_response.add(SimpleResponse(response, response))
        dialogflow_response.expect_user_response = expect_user_response
        return dialogflow_response.get_final_response()

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
                if self.bus_response.Service.size > Constants.MAX_BUSES:
                    self.bus_response = self.bus_response.head(Constants.MAX_BUSES)
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

