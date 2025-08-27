#!/usr/bin/env python3
"""
Test for InfluxDB output transport
"""

import time
import unittest
from protocol_gateway import CustomConfigParser as ConfigParser
from unittest.mock import MagicMock, Mock, patch

from classes.transports.influxdb_out import influxdb_out


class TestInfluxDBOut(unittest.TestCase):
    """Test cases for InfluxDB output transport"""

    def setUp(self):
        """Set up test fixtures"""
        self.config = ConfigParser()
        self.config.add_section('influxdb_output')
        self.config.set('influxdb_output', 'type', 'influxdb_out')
        self.config.set('influxdb_output', 'host', 'localhost')
        self.config.set('influxdb_output', 'port', '8086')
        self.config.set('influxdb_output', 'database', 'test_db')

    #@patch('classes.transports.influxdb_out.InfluxDBClient')
    #@patch('classes.transports.influxdb_out.InfluxDBClient')
    @patch('classes.transports.influxdb_out.InfluxDBClient')
    def test_connect_success(self, mock_influxdb_client):
        """Test successful connection to InfluxDB"""
        # Mock the InfluxDB client
        mock_client = Mock()
        mock_influxdb_client.return_value = mock_client
        mock_client.get_list_database.return_value = [{'name': 'test_db'}]

        transport = influxdb_out(self.config['influxdb_output'])
        transport.connect()

        self.assertTrue(transport.connected)
        mock_influxdb_client.assert_called_once_with(
            host='localhost',
            port=8086,
            username=None,
            password=None,
            database='test_db',
            timeout=10
        )

    @patch('classes.transports.influxdb_out.InfluxDBClient')
    def test_connect_database_creation(self, mock_influxdb_client):
        """Test database creation when it doesn't exist"""
        # Mock the InfluxDB client
        mock_client = Mock()
        mock_influxdb_client.return_value = mock_client
        mock_client.get_list_database.return_value = [{'name': 'other_db'}]

        transport = influxdb_out(self.config['influxdb_output'])
        transport.connect()

        self.assertTrue(transport.connected)
        mock_client.create_database.assert_called_once_with('test_db')

    @patch('classes.transports.influxdb_out.InfluxDBClient')
    def test_write_data_batching(self, mock_influxdb_client):
        """Test data writing and batching"""
        # Mock the InfluxDB client
        mock_client = Mock()
        mock_influxdb_client.return_value = mock_client
        mock_client.get_list_database.return_value = [{'name': 'test_db'}]

        transport = influxdb_out(self.config['influxdb_output'])
        transport.connect()


        # Mock source transport
        source_transport = Mock()
        source_transport.transport_name = 'test_source'
        source_transport.device_identifier = 'test123'
        source_transport.device_name = 'Test Device'
        source_transport.device_manufacturer = 'Test Manufacturer'
        source_transport.device_model = 'Test Model'
        source_transport.device_serial_number = '123456'

        mock_protocol_settings = Mock()
        mock_protocol_settings.get_registry_map.return_value = []  # or list of entries if you want
        source_transport.protocolSettings = mock_protocol_settings

        # Test data
        test_data = {'battery_voltage': '48.5', 'battery_current': '10.2'}

        transport.last_batch_time = time.time() #stop "flush" from happening and failing test
        transport.batch_timeout = 21
        transport.write_data(test_data, source_transport)

        # Check that data was added to batch
        self.assertEqual(len(transport.batch_points), 1)
        point = transport.batch_points[0]

        self.assertEqual(point['measurement'], 'device_data')
        self.assertIn('device_identifier', point['tags'])
        self.assertIn('battery_voltage', point['fields'])
        self.assertIn('battery_current', point['fields'])

        # Check data type conversion
        self.assertEqual(point['fields']['battery_voltage'], 48.5)
        self.assertEqual(point['fields']['battery_current'], 10.2)

    def test_configuration_options(self):
        """Test configuration option parsing"""
        # Add more configuration options
        self.config.set('influxdb_output', 'username', 'admin')
        self.config.set('influxdb_output', 'password', 'secret')
        self.config.set('influxdb_output', 'measurement', 'custom_measurement')
        self.config.set('influxdb_output', 'batch_size', '50')
        self.config.set('influxdb_output', 'batch_timeout', '5.0')

        transport = influxdb_out(self.config['influxdb_output'])

        self.assertEqual(transport.username, 'admin')
        self.assertEqual(transport.password, 'secret')
        self.assertEqual(transport.measurement, 'custom_measurement')
        self.assertEqual(transport.batch_size, 50)
        self.assertEqual(transport.batch_timeout, 5.0)


if __name__ == '__main__':
    unittest.main() 