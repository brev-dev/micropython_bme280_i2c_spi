# Author(s): Jonathan Hanson 2018
# SPI added by Neville Barker 2020
# This is more or less a straight read of the Bosch data sheet at:
# https://www.bosch-sensortec.com/bst/products/all_products/bme280
# and specifically:
# https://ae-bst.resource.bosch.com/media/_tech/media/datasheets/BST-BME280_DS001-12.pdf
#
# Modeled on the reference library Bosch Sensortec C library at:
# https://github.com/BoschSensortec/BME280_driver
#
# The development of this module was heavily guided by the prior work done
# by Peter Dahlberg et al at:
# https://github.com/catdog2/mpy_bme280_esp8266

from micropython import const
from ustruct import unpack, unpack_from
from utime import sleep_ms


# BME280 default address
BME280_I2C_ADDR_PRIM                  = const(0x76)
BME280_I2C_ADDR_SEC                   = const(0x77)

# Sensor Power Mode Options
BME280_SLEEP_MODE                     = const(0x00)
BME280_FORCED_MODE                    = const(0x01)
BME280_NORMAL_MODE                    = const(0x03)

# Oversampling Options
BME280_NO_OVERSAMPLING                = const(0x00)
BME280_OVERSAMPLING_1X                = const(0x01)
BME280_OVERSAMPLING_2X                = const(0x02)
BME280_OVERSAMPLING_4X                = const(0x03)
BME280_OVERSAMPLING_8X                = const(0x04)
BME280_OVERSAMPLING_16X               = const(0x05)

# Standby Duration Options
BME280_STANDBY_TIME_500_US            = const(0x00)  # Note this is microseconds, so 0.5 ms
BME280_STANDBY_TIME_62_5_MS           = const(0x01)
BME280_STANDBY_TIME_125_MS            = const(0x02)
BME280_STANDBY_TIME_250_MS            = const(0x03)
BME280_STANDBY_TIME_500_MS            = const(0x04)
BME280_STANDBY_TIME_1000_MS           = const(0x05)
BME280_STANDBY_TIME_10_MS             = const(0x06)
BME280_STANDBY_TIME_20_MS             = const(0x07)

# Filter Coefficient Options
BME280_FILTER_COEFF_OFF               = const(0x00)
BME280_FILTER_COEFF_2                 = const(0x01)
BME280_FILTER_COEFF_4                 = const(0x02)
BME280_FILTER_COEFF_8                 = const(0x03)
BME280_FILTER_COEFF_16                = const(0x04)

# BME280 Chip ID
_BME280_CHIP_ID                       = const(0x60)

# BME280 reset value
_BME280_RESET_VALUE                   = const(0xB6)

# Register Addresses
_BME280_CHIP_ID_ADDR                  = const(0xD0)
_BME280_RESET_ADDR                    = const(0xE0)
_BME280_TEMP_PRESS_CALIB_DATA_ADDR    = const(0x88)
_BME280_HUMIDITY_CALIB_DATA_ADDR      = const(0xE1)
_BME280_PWR_CTRL_ADDR                 = const(0xF4)
_BME280_CTRL_HUM_ADDR                 = const(0xF2)
_BME280_CTRL_MEAS_ADDR                = const(0xF4)
_BME280_CONFIG_ADDR                   = const(0xF5)
_BME280_DATA_ADDR                     = const(0xF7)

# Register range sizes
_BME280_TEMP_PRESS_CALIB_DATA_LEN     = const(26)
_BME280_HUMIDITY_CALIB_DATA_LEN       = const(7)
_BME280_P_T_H_DATA_LEN                = const(8)

def set_bit(v, index, x):
	"""Set the index:th bit of v to 1 if x is truthy, else to 0, and return the new value."""
	mask = 1 << index   # Compute mask, an integer with just bit 'index' set.
	v &= ~mask          # Clear the bit indicated by the mask (if x is False)
	if x:
		v |= mask         # If x was True, set the bit indicated by the mask.
	return v            # Return the result, we're done.


class BME280_I2C_SPI:
	def __init__(self, i2c_address: int = BME280_I2C_ADDR_PRIM, i2c=None, spi=None, spi_cs=None):
		"""
		Ensure I2C communication with the sensor is working, reset the sensor,
		and load its calibration data into memory.
		"""
		assert i2c is None or spi is None, 'Only specify either I2C or SPI, not both.'
		assert i2c is not None or spi is not None, 'A configured I2C or SPI object is required.'
		if spi is not None and spi_cs is None:
			raise ValueError('A configured Cable Select pin object is required for SPI.')

		self.i2c = i2c
		self.i2c_address = i2c_address
		self.spi = spi
		self.spi_cs = spi_cs

		self._read_chip_id()
		self._soft_reset()
		self._load_calibration_data()

	def bme_read(self, start_address, nbytes, check_spi_cs=True):
		"""
		Read nbytes of data from the specified register start_address, using either i2c or spi.
		If using spi, ensure the device is deselected before starting, if check_spi_cs is True.
		"""
		if self.i2c is not None: #i2c read
			return self.i2c.readfrom_mem(self.i2c_address, start_address, nbytes)
		else: #spi read
			if check_spi_cs and not self.spi_cs.value(): self.spi_cs.on() #ensure spi device is not already selected
			#to specify read mode, bit 7 of the register address must be set high
			start_address=set_bit(start_address, 7, True)
			self.spi_cs.off() #select spi device
			self.spi.write(bytes((start_address,))) #tell it where to start reading
			spi_out=self.spi.read(nbytes) #read output
			self.spi_cs.on() #deselect spi device
			return spi_out

	def bme_write(self, start_address, byte_list, check_spi_cs=True):
		"""
		Write byte_list data starting at the specified register start_address, using either i2c or spi.
		If using spi, ensure the device is deselected before starting, if check_spi_cs is True.
		"""
		if self.i2c is not None: #i2c write
			self.i2c.writeto_mem(self.i2c_address, start_address, bytearray(byte_list))
		else: #spi write
			if check_spi_cs and not self.spi_cs.value(): self.spi_cs.on() #ensure spi device is not already selected
			#to specify write mode, bit 7 of the register address must be set low
			start_address=set_bit(start_address, 7, False)
			#data are written in pairs of address, value1, address+1, value2 etc.
			outdata=[] #prepare the output list
			for i, cbyte in enumerate(byte_list):
				outdata.extend([start_address+i, cbyte])
			self.spi_cs.off() #select spi device
			self.spi.write(bytearray(outdata)) #write data
			self.spi_cs.on() #deselect spi device

	def _read_chip_id(self):
		"""
		Read the chip ID from the sensor and verify it's correct.
		If the value isn't correct, wait 1ms and try again.
		If 5 tries don't work, raise an exception.
		"""
		for x in range(5):
			mem = self.bme_read(_BME280_CHIP_ID_ADDR, 1)
			if mem[0] == _BME280_CHIP_ID:
				return
			sleep_ms(1)
		raise Exception("Couldn't read BME280 chip ID after 5 attempts.")

	def _soft_reset(self):
		"""
		Write the reset command to the sensor's reset address.
		Wait 2ms, per the reference library's example.
		"""
		self.bme_write(_BME280_RESET_ADDR, [_BME280_RESET_VALUE])
		sleep_ms(2)

	def _load_calibration_data(self):
		"""
		Load the read-only calibration values out of the sensor's memory, to be
		used later in calibrating the raw reads.  These get stored in various
		self.cal_dig_* object properties.

		See https://github.com/BoschSensortec/BME280_driver/blob/bme280_v3.3.4/bme280.c#L1192
		See https://github.com/BoschSensortec/BME280_driver/blob/bme280_v3.3.4/bme280.c#L1216
		See https://github.com/catdog2/mpy_bme280_esp8266/blob/master/bme280.py#L73
		"""
		# Load the temperature and pressure calibration data
		# (note that the first value of the humidity data is stuffed in here)
		tp_cal_mem = self.bme_read(	_BME280_TEMP_PRESS_CALIB_DATA_ADDR,
									_BME280_TEMP_PRESS_CALIB_DATA_LEN)

		(self.cal_dig_T1, self.cal_dig_T2, self.cal_dig_T3,
			self.cal_dig_P1, self.cal_dig_P2, self.cal_dig_P3,
			self.cal_dig_P4, self.cal_dig_P5, self.cal_dig_P6,
			self.cal_dig_P7, self.cal_dig_P8, self.cal_dig_P9,
			_,
			self.cal_dig_H1) = unpack("<HhhHhhhhhhhhBB", tp_cal_mem)

		# Load the rest of the humidity calibration data
		hum_cal_mem = self.bme_read(_BME280_HUMIDITY_CALIB_DATA_ADDR,
									_BME280_HUMIDITY_CALIB_DATA_LEN)

		self.cal_dig_H2, self.cal_dig_H3 = unpack("<hB", hum_cal_mem)

		e4_sign = unpack_from("<b", hum_cal_mem, 3)[0]
		self.cal_dig_H4 = (e4_sign << 4) | (hum_cal_mem[4] & 0b00001111)

		e6_sign = unpack_from("<b", hum_cal_mem, 5)[0]
		self.cal_dig_H5 = (e6_sign << 4) | (hum_cal_mem[4] >> 4)

		self.cal_dig_H6 = unpack_from("<b", hum_cal_mem, 6)[0]

		# Initialize the cal_t_fine carry-over value used during compensation
		self.cal_t_fine = 0

	def get_measurement_settings(self):
		"""
		Return a parsed set of the sensor's measurement settings as a dict
		These values include oversampling settings for each measurement,
		the IIR filter coefficient, and the standby duration for normal
		power mode.
		See the data sheet, section 3 and 5
		"""
		mem = self.bme_read(_BME280_CTRL_HUM_ADDR, 4)
		ctrl_hum, _, ctrl_meas, config = unpack("<BBBB", mem)

		return {
			"osr_h":        (ctrl_hum & 0b00000111),
			"osr_p":        (ctrl_meas >> 2) & 0b00000111,
			"osr_t":        (ctrl_meas >> 5) & 0b00000111,
			"filter":       (config >> 2) & 0b00000111,
			"standby_time": (config >> 5) & 0b00000111,
		}

	def set_measurement_settings(self, settings: dict):
		"""
		Set the sensor's settings for each measurement's oversampling,
		the pressure IIR filter coefficient, and standby duration
		during normal power mode.

		The settings dict can have keys osr_h, osr_p, osr_t, filter, and
		standby_time.  All values are optional, and omitting any will retain
		the pre-existing value.

		See the data sheet, section 3 and 5
		"""
		self._validate_settings(settings)
		self._ensure_sensor_is_asleep()
		self._write_measurement_settings(settings)

	def _validate_settings(self, settings: dict):
		oversampling_options = [
			BME280_NO_OVERSAMPLING, BME280_OVERSAMPLING_1X,
			BME280_OVERSAMPLING_2X, BME280_OVERSAMPLING_4X,
		BME280_OVERSAMPLING_8X, BME280_OVERSAMPLING_16X]

		filter_options = [
			BME280_FILTER_COEFF_OFF, BME280_FILTER_COEFF_2,
			BME280_FILTER_COEFF_4, BME280_FILTER_COEFF_8,
			BME280_FILTER_COEFF_16]

		standby_time_options = [
			BME280_STANDBY_TIME_500_US,
			BME280_STANDBY_TIME_62_5_MS, BME280_STANDBY_TIME_125_MS,
			BME280_STANDBY_TIME_250_MS, BME280_STANDBY_TIME_500_MS,
			BME280_STANDBY_TIME_1000_MS, BME280_STANDBY_TIME_10_MS,
			BME280_STANDBY_TIME_20_MS]

		if 'osr_h' in settings:
			if settings['osr_h'] not in oversampling_options:
				raise ValueError("osr_h must be one of the oversampling defines")
		if 'osr_p' in settings:
			if settings['osr_h'] not in oversampling_options:
				raise ValueError("osr_p must be one of the oversampling defines")
		if 'osr_t' in settings:
			if settings['osr_h'] not in oversampling_options:
				raise ValueError("osr_t must be one of the oversampling defines")
		if 'filter' in settings:
			if settings['filter'] not in filter_options:
				raise ValueError("filter filter coefficient defines")
		if 'standby_time' in settings:
			if settings['standby_time'] not in standby_time_options:
				raise ValueError("standby_time must be one of the standby time duration defines")

	def _write_measurement_settings(self, settings: dict):
		# Read in the existing configuration, to modify
		mem = self.bme_read(_BME280_CTRL_HUM_ADDR, 4)
		ctrl_hum, _, ctrl_meas, config = unpack("<BBBB", mem)

		# Make any changes necessary to the ctrl_hum register
		if "osr_h" in settings:
			newval = (ctrl_hum & 0b11111000) | (settings['osr_h'] & 0b00000111)
			self.bme_write(_BME280_CTRL_HUM_ADDR, [newval])

			# according to the data sheet, ctrl_hum needs a write to
			# ctrl_meas in order to take effect
			self.bme_write(_BME280_CTRL_MEAS_ADDR, [ctrl_meas])

		# Make any changes necessary to the ctrl_meas register
		if "osr_p" in settings or "osr_t" in settings:
			newval = ctrl_meas
			if "osr_p" in settings:
				newval = (newval & 0b11100011) | ((settings['osr_p'] << 2) & 0b00011100)
			if "osr_t" in settings:
				newval = (newval & 0b00011111) | ((settings['osr_t'] << 5) & 0b11100000)
			self.bme_write(_BME280_CTRL_MEAS_ADDR, [newval])

		# Make any changes necessary to the config register
		if "filter" in settings or "standby_time" in settings:
			newval = config
			if "filter" in settings:
				newval = (newval & 0b11100011) | ((settings['filter'] << 2) & 0b00011100)
			if "standby_time" in settings:
				newval = (newval & 0b00011111) | ((settings['standby_time'] << 5) & 0b11100000)
			self.bme_write(_BME280_CONFIG_ADDR, [newval])

	def get_power_mode(self):
		"""
		Result will be one of BME280_SLEEP_MODE, BME280_FORCED_MODE, or
		BME280_NORMAL_MODE.
		See the data sheet, section 3.3
		"""
		mem = self.bme_read(_BME280_PWR_CTRL_ADDR, 1)
		return (mem[0] & 0b00000011)

	def set_power_mode(self, new_power_mode: int):
		"""
		Configure the sensor's power mode (BME280_SLEEP_MODE,
		BME280_FORCED_MODE, or BME280_NORMAL_MODE)

		Note that setting to forced mode will immediately set the sensor back
		to sleep mode after taking a measurement.

		See the data sheet, section 3.3
		"""
		if new_power_mode not in [BME280_SLEEP_MODE, BME280_FORCED_MODE, BME280_NORMAL_MODE]:
			raise ValueError("New power mode must be sleep, forced, or normal constant")

		self._ensure_sensor_is_asleep()

		# Read the current register, mask out and set the new power mode,
		# and write the register back to the device.
		mem = self.bme_read(_BME280_PWR_CTRL_ADDR, 1)
		newval = (mem[0] & 0b11111100) | (new_power_mode & 0b00000011)
		self.bme_write(_BME280_PWR_CTRL_ADDR, [newval])

	def _ensure_sensor_is_asleep(self):
		"""
		If the sensor mode isn't already "sleep", then put it to sleep.

		This is done by reading out the configuration values we want to keep,
		and then doing a soft reset and writing those values back.
		"""
		if self.get_power_mode() != BME280_SLEEP_MODE:
			settings = self.get_measurement_settings()
			self._soft_reset()
			self._write_measurement_settings(settings)

	def get_measurement(self):
		"""
		Return a set of measurements in decimal value, compensated with the
		sensor's stored calibration data.
		"""
		uncompensated_data = self._read_uncompensated_data()

		# Be sure to call self._compensate_temperature() first, as it sets a
		# global "fine" calibration value for the other two compensation
		# functions
		return {
			"temperature": self._compensate_temperature(uncompensated_data['temperature']),
			"pressure":    self._compensate_pressure(uncompensated_data['pressure']),
			"humidity":    self._compensate_humidity(uncompensated_data['humidity']),
		}

	def _read_uncompensated_data(self):
		# Read the uncompensated temperature, pressure, and humidity data
		mem = self.bme_read(_BME280_DATA_ADDR, _BME280_P_T_H_DATA_LEN)
		(press_msb, press_lsb, press_xlsb,
			temp_msb, temp_lsb, temp_xlsb,
			hum_msb, hum_lsb) = unpack("<BBBBBBBB", mem)

		# Assemble the values from the memory fragments and return a dict.
		#
		# Note that we're calling temperature first, since it sets the
		# cal_t_fine value used in humidity and pressure.
		return {
			"temperature": (temp_msb << 12) | (temp_lsb << 4) | (temp_xlsb >> 4),
			"pressure":    (press_msb << 12) | (press_lsb << 4) | (press_xlsb >> 4),
			"humidity":    (hum_msb << 8) | (hum_lsb),
		}

	def _compensate_temperature(self, adc_T: int) -> float:
		"""
		Output value of “25.0” equals 25.0 DegC.

		See the integer implementation in the data sheet, section 4.2.3
		And the reference library:
		https://github.com/BoschSensortec/BME280_driver/blob/bme280_v3.3.4/bme280.c#L987
		"""
		temperature_min = -4000
		temperature_max = 8500

		var1 = (((adc_T // 8) - (self.cal_dig_T1 * 2)) * self.cal_dig_T2) // 2048

		var2 = (((((adc_T // 16) - self.cal_dig_T1) * ((adc_T // 16) - self.cal_dig_T1)) // 4096) * self.cal_dig_T3) // 16384

		self.cal_t_fine = var1 + var2

		temperature = (self.cal_t_fine * 5 + 128) // 256

		if temperature < temperature_min:
			temperature = temperature_min
		elif temperature > temperature_max:
			temperature = temperature_max

		return temperature / 100

	def _compensate_pressure(self, adc_P: int) -> float:
		"""
		Output value of “96386.0” equals 96386 Pa = 963.86 hPa

		See the 32-bit integer implementation in the data sheet, section 4.2.3
		And the reference library:
		https://github.com/BoschSensortec/BME280_driver/blob/bme280_v3.3.4/bme280.c#L1059

		Note that there's a 64-bit version of this function in the reference
		library on line 1016 that we're leaving unimplemented.
		"""
		pressure_min = 30000
		pressure_max = 110000

		var1 = (self.cal_t_fine // 2) - 64000

		var2 = (((var1 // 4) * (var1 // 4)) // 2048) * self.cal_dig_P6
		var2 = var2 + ((var1 * self.cal_dig_P5) * 2)
		var2 = (var2 // 4) + (self.cal_dig_P4 * 65536)

		var3 = (self.cal_dig_P3 * (((var1 // 4) * (var1 // 4)) // 8192)) // 8

		var4 = (self.cal_dig_P2 * var1) // 2

		var1 = (var3 + var4) // 262144
		var1 = ((32768 + var1) * self.cal_dig_P1) // 32768

		# avoid exception caused by division by zero
		if var1:
			var5 = 1048576 - adc_P

			pressure = (var5 - (var2 // 4096)) * 3125

			if pressure < 0x80000000:
				pressure = (pressure << 1) // var1
			else:
				pressure = (pressure // var1) * 2

			var1 = (self.cal_dig_P9 * (((pressure // 8) * (pressure // 8)) // 8192)) // 4096

			var2 = (((pressure // 4)) * self.cal_dig_P8) // 8192

			pressure = pressure + ((var1 + var2 + self.cal_dig_P7) // 16)

			if pressure < pressure_min:
				pressure = pressure_min
			elif pressure > pressure_max:
				pressure = pressure_max

		else: # Invalid case
			pressure = pressure_min

		return pressure

	def _compensate_humidity(self, adc_H: int) -> float:
		"""
		Output value between 0.0 and 100.0, where 100.0 is 100%RH

		See the floating-point implementation in the reference library:
		https://github.com/BoschSensortec/BME280_driver/blob/bme280_v3.3.4/bme280.c#1108
		"""

		humidity_max = 102400

		var1 = self.cal_t_fine - 76800

		var2 = adc_H * 16384

		var3 = self.cal_dig_H4 * 1048576

		var4 = self.cal_dig_H5 * var1

		var5 = (((var2 - var3) - var4) + 16384) // 32768

		var2 = (var1 * self.cal_dig_H6) // 1024

		var3 = (var1 * self.cal_dig_H3) // 2048

		var4 = ((var2 * (var3 + 32768)) // 1024) + 2097152

		var2 = ((var4 * self.cal_dig_H2) + 8192) // 16384

		var3 = var5 * var2

		var4 = ((var3 // 32768) * (var3 // 32768)) // 128

		var5 = var3 - ((var4 * self.cal_dig_H1) // 16)
		if var5 < 0:
			var5 = 0
		if var5 > 419430400:
			var5 = 419430400

		humidity = var5 // 4096

		if (humidity > humidity_max):
			humidity = humidity_max

		return humidity / 1024
