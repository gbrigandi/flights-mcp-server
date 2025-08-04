from typing import Any
import httpx
import subprocess
import sys
import json
import os
import asyncio
from mcp.server.fastmcp import FastMCP

from fast_flights import FlightData, Passengers, Result, create_filter, get_flights_from_filter, search_airport
from dataclasses import asdict

from datetime import datetime


# initialize the MCP server
mcp = FastMCP("flights")


# Helper Functions

def ensure_playwright_browsers():
    """
    Ensures that Playwright browsers (specifically Chromium) are installed.
    If not installed, attempts to install them automatically.
    
    Returns:
        bool: True if browsers are available, False otherwise
    """
    try:
        # Check if playwright is available and browsers are installed
        result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        # If dry-run succeeds without needing to download, browsers are already installed
        if result.returncode == 0 and "is already installed" in result.stdout:
            return True
            
        # If browsers need to be installed, install them
        print("Installing Playwright Chromium browser...")
        install_result = subprocess.run(
            [sys.executable, "-m", "playwright", "install", "chromium"],
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout for installation
        )
        
        if install_result.returncode == 0:
            print("Playwright Chromium browser installed successfully!")
            return True
        else:
            print(f"Failed to install Playwright browsers: {install_result.stderr}")
            return False
            
    except subprocess.TimeoutExpired:
        print("Timeout occurred while installing Playwright browsers")
        return False
    except FileNotFoundError:
        print("Playwright CLI not found. Make sure playwright is installed.")
        return False
    except Exception as e:
        print(f"Error checking/installing Playwright browsers: {str(e)}")
        return False


def check_playwright_setup():
    """
    Checks if Playwright setup is complete and attempts to fix it if not.
    This function is called before making flight requests.
    
    Returns:
        bool: True if setup is complete, False otherwise
    """
    try:
        # First check if playwright module is available
        import playwright
        
        # Then ensure browsers are installed
        return ensure_playwright_browsers()
        
    except ImportError:
        print("Playwright is not installed. Please install it with: pip install playwright")
        return False
    except Exception as e:
        print(f"Error during Playwright setup check: {str(e)}")
        return False


def format_flight_info(flight_data, origin_airport, destination_airport):
    """
    Formats flight information into a human-readable string.

    Args:
        flight_data: Dictionary containing flight information
        origin_airport: Name of Origin airport city and IATA code (ex: "Seattle (SEA)")
        destination_airport: Name of Destination airport city and IATA code (ex: "Tokyo (HND)")

    Returns:
        Formatted string describing the flight
    """
    
    duration_parts = flight_data['duration'].split()
    
    if len(duration_parts) == 4:
        duration_formatted = f"{duration_parts[0]} hours and {duration_parts[2]} minutes"
    else:
        duration_formatted = flight_data['duration']
    
    # Reformat departure and arrival dates
    def expand_date(date_str):
        # Map abbreviated month and day
        month_map = {
            'Jan': 'January', 'Feb': 'February', 'Mar': 'March', 
            'Apr': 'April', 'May': 'May', 'Jun': 'June', 
            'Jul': 'July', 'Aug': 'August', 'Sep': 'September', 
            'Oct': 'October', 'Nov': 'November', 'Dec': 'December'
        }
        day_map = {'Mon': 'Monday', 'Tue': 'Tuesday', 'Wed': 'Wednesday', 
                   'Thu': 'Thursday', 'Fri': 'Friday', 'Sat': 'Saturday', 
                   'Sun': 'Sunday'}
        
        parts = date_str.split()
        time = f"{parts[0]} {parts[1]}"  # "9:40 AM"
        
        # Handle the day abbreviation (removing the comma)
        day_abbr = parts[3].rstrip(',')  # "Sat" (removing comma from "Sat,")
        month_abbr = parts[4]  # "Apr"
        day = parts[5]  # "5"
        
        full_day = day_map.get(day_abbr, day_abbr)
        full_month = month_map.get(month_abbr, month_abbr)
        
        # Add ordinal suffix to the day
        day_with_suffix = day + ('th' if not day.endswith(('1', '2', '3')) or day.endswith(('11', '12', '13')) else 
                                 ('st' if day.endswith('1') else 
                                  ('nd' if day.endswith('2') else 
                                   ('rd' if day.endswith('3') else 'th'))))
        
        return f"{time} on {full_day}, {full_month} {day_with_suffix}"
    
    # Determine best flight qualifier
    best_flight_qualifier = "considered one of the best options by Google Flights" if flight_data['is_best'] else "an available option"
    
    # Handle potential None or empty values
    stops = flight_data["stops"]
    stops_text = f"{stops} stop{'s' if stops != 1 else ''}" if stops > 0 else "non-stop"
    
    formatted_string = (
        f"This flight departs at {expand_date(flight_data['departure'])} from {origin_airport}, local time, "
        f"and arrives at {expand_date(flight_data['arrival'])} in {destination_airport}, local time. "
        f"The flight is operated by {flight_data['name']} and has a duration of {duration_formatted} "
        f"with {stops_text} in between. "
        f"And it's price is {flight_data['price']} and is {best_flight_qualifier}!"
    )
    
    return formatted_string





# Main Functions

@mcp.tool()
async def get_general_flights_info(origin: str, destination: str, departure_date: str,
                      trip_type: str = "one-way", seat: str = "economy",
                      adults: int = 1, children: int = 0, infants_in_seat: int = 0, infants_on_lap: int = 0,
                      n_flights: int = 40) -> list[str]:
    """ Get general/comprehensive flight information for N flights for a given origin, destination, and departure date. If the user wants to do a round-trip,
    you will need to make two one-way trip calls.

    Args:
        origin (str): The origin airport IATA code (ex: "ATL", "SCL", "JFK").
        destination (str): The destination airport IATA code (ex: "DTW", "ICN", "LIR").
        departure_date (str): The departure date in YYYY-MM-DD format.

        trip_type (str, optional): The type of trip ("one-way" or "round-trip" only). Defaults to "one-way".
        seat (str, optional): The type of seat ("economy", "premium-economy", "business", or "first" only). Defaults to "economy".
        adults (int, optional): The number of adults. Defaults to 1.
        children (int, optional): The number of children. Defaults to 0.
        infants_in_seat (int, optional): The number of infants in a seat. Defaults to 0.
        infants_lap (int, optional): The number of infants on a lap. Defaults to 0.

        n_flights (int, optional): The number of flights to return. Defaults to 25.

    Returns:
        list[str]: A list of flight information strings.
    """

    if (len(origin) != 3 or len(destination) != 3):
        return ["Origin and destination must be 3 characters."]
    
    if (len(departure_date) != 10 or departure_date[4] != '-' or departure_date[7] != '-'):
        return ["Departure date must be in YYYY-MM-DD format."]
    
    if (trip_type != "one-way" and trip_type != "round-trip"):
        return ["Trip type must be either 'one-way' or 'round-trip'."]
    
    if (seat != "economy" and seat != "premium-economy" and seat != "business" and seat != "first"):
        return ["Seat type must be either 'economy', 'premium-economy', 'business', or 'first'."]
    

    try:
        
        # Make API call to Google Flights via fast-flights

        flight_data_input = [FlightData(date=departure_date, from_airport=origin, to_airport=destination)]
        
        passengers_input = Passengers(adults=adults, children=children, infants_in_seat=infants_in_seat, infants_on_lap=infants_on_lap)

        # Create filter first, then get flights
        filter = create_filter(
            flight_data=flight_data_input,
            trip=trip_type,
            seat=seat,
            passengers=passengers_input
        )
        
        result: Result = await asyncio.to_thread(get_flights_from_filter, filter, mode="local")
        
        result = asdict(result)
        
        if not result or "flights" not in result:
            return ["No flight data available for the specified route and dates."]

        current_price = result["current_price"]
        all_flights = result["flights"]

        if not all_flights:
            return ["No flights found for the specified route and dates."]

        top_n_flights = all_flights[0: min(n_flights, len(all_flights))]

        flight_info = []

        origin_airport = origin
        destination_airport = destination

        for flight in top_n_flights:
            flight_info.append(format_flight_info(flight, origin_airport, destination_airport))

        output = [f"The current overall flight prices for this route and time are: {str(current_price)}."] + flight_info


        return output


    except httpx.RequestError:
        return ["Unable to connect to the flight search service. Please try again later."]
    
    except ValueError as e:
        return [f"Invalid data received: {str(e)}"]
    
    except Exception as e:
        return [f"An unexpected error occurred while searching for flights: {str(e)}"]



@mcp.tool()
async def get_cheapest_flights(origin: str, destination: str, departure_date: str,
                      trip_type: str = "one-way", seat: str = "economy",
                      adults: int = 1, children: int = 0, infants_in_seat: int = 0, infants_on_lap: int = 0) -> list[str]:
   
    """ Get the cheapest flight information for a given origin, destination, and departure date. If the user wants to do a round-trip,
    you will need to make two one-way trip calls.

    Args:
        origin (str): The origin airport IATA code (ex: "ATL", "SCL", "JFK").
        destination (str): The destination airport IATA code (ex: "DTW", "ICN", "LIR").
        departure_date (str): The departure date in YYYY-MM-DD format.

        trip_type (str, optional): The type of trip ("one-way" or "round-trip" only). Defaults to "one-way".
        seat (str, optional): The type of seat ("economy", "premium-economy", "business", or "first" only). Defaults to "economy".
        adults (int, optional): The number of adults. Defaults to 1.
        children (int, optional): The number of children. Defaults to 0.
        infants_in_seat (int, optional): The number of infants in a seat. Defaults to 0.
        infants_lap (int, optional): The number of infants on a lap. Defaults to 0.

    Returns:
        list[str]: A list of flight information strings.
    """

    if (len(origin) != 3 or len(destination) != 3):
        return ["Origin and destination must be 3 characters."]
    
    if (len(departure_date) != 10 or departure_date[4] != '-' or departure_date[7] != '-'):
        return ["Departure date must be in YYYY-MM-DD format."]
    
    if (trip_type != "one-way" and trip_type != "round-trip"):
        return ["Trip type must be either 'one-way' or 'round-trip'."]
    
    if (seat != "economy" and seat != "premium-economy" and seat != "business" and seat != "first"):
        return ["Seat type must be either 'economy', 'premium-economy', 'business', or 'first'."]

    try:
        # Make API call to Google Flights via fast-flights

        flight_data_input = [FlightData(date=departure_date, from_airport=origin, to_airport=destination)]
        passengers_input = Passengers(adults=adults, children=children, infants_in_seat=infants_in_seat, infants_on_lap=infants_on_lap)

        # Create filter first, then get flights
        filter = create_filter(
            flight_data=flight_data_input,
            trip=trip_type,
            seat=seat,
            passengers=passengers_input
        )
        
        result: Result = await asyncio.to_thread(get_flights_from_filter, filter, mode="local")
        
        result = asdict(result)
        
        if not result or "flights" not in result:
            return ["No flight data available for the specified route and dates."]

        all_flights = result["flights"]

        if not all_flights:
            return ["No flights found for the specified route and dates."]

        def get_price_value(flight):
            price_str = flight.get('price')
            if not price_str or price_str == 'Price unavailable':
                return float('inf')
            
            # Remove $ and any commas from the price string
            price_str = price_str.replace('$', '').replace(',', '')
            
            try:
                return float(price_str)
            except (ValueError, TypeError):
                return float('inf')

        price_sorted_flights = sorted(all_flights, key=get_price_value)

        top_n_flights = price_sorted_flights[0: min(30, len(price_sorted_flights))]

        flight_info = []

        origin_airport = origin
        destination_airport = destination

        for flight in top_n_flights:
            flight_info.append(format_flight_info(flight, origin_airport, destination_airport))

        output = ["Here are the cheapest flights for this route and time: "] + flight_info


        return output



    except httpx.RequestError:
        return ["Unable to connect to the flight search service. Please try again later."]
    
    except ValueError as e:
        return [f"Invalid data received: {str(e)}"]
    
    except Exception as e:
        return [f"An unexpected error occurred while searching for flights: {str(e)}"]


@mcp.tool()
async def get_best_flights(origin: str, destination: str, departure_date: str,
                      trip_type: str = "one-way", seat: str = "economy",
                      adults: int = 1, children: int = 0, infants_in_seat: int = 0, infants_on_lap: int = 0) -> list[str]:
   
    """ Get the best flights as determined by Google Flights for a given origin, destination, and departure date. If the user wants to do a round-trip,
    you will need to make two one-way trip calls.

    Args:
        origin (str): The origin airport IATA code (ex: "ATL", "SCL", "JFK").
        destination (str): The destination airport IATA code (ex: "DTW", "ICN", "LIR").
        departure_date (str): The departure date in YYYY-MM-DD format.

        trip_type (str, optional): The type of trip ("one-way" or "round-trip" only). Defaults to "one-way".
        seat (str, optional): The type of seat ("economy", "premium-economy", "business", or "first" only). Defaults to "economy".
        adults (int, optional): The number of adults. Defaults to 1.
        children (int, optional): The number of children. Defaults to 0.
        infants_in_seat (int, optional): The number of infants in a seat. Defaults to 0.
        infants_lap (int, optional): The number of infants on a lap. Defaults to 0.

    Returns:
        list[str]: A list of flight information strings.
    """

    if (len(origin) != 3 or len(destination) != 3):
        return ["Origin and destination must be 3 characters."]
    
    if (len(departure_date) != 10 or departure_date[4] != '-' or departure_date[7] != '-'):
        return ["Departure date must be in YYYY-MM-DD format."]
    
    if (trip_type != "one-way" and trip_type != "round-trip"):
        return ["Trip type must be either 'one-way' or 'round-trip'."]
    
    if (seat != "economy" and seat != "premium-economy" and seat != "business" and seat != "first"):
        return ["Seat type must be either 'economy', 'premium-economy', 'business', or 'first'."]

    try:
        # Make API call to Google Flights via fast-flights

        flight_data_input = [FlightData(date=departure_date, from_airport=origin, to_airport=destination)]

        passengers_input = Passengers(adults=adults, children=children, infants_in_seat=infants_in_seat, infants_on_lap=infants_on_lap)

        # Create filter first, then get flights
        filter = create_filter(
            flight_data=flight_data_input,
            trip=trip_type,
            seat=seat,
            passengers=passengers_input
        )
        
        result: Result = await asyncio.to_thread(get_flights_from_filter, filter, mode="local")
        
        result = asdict(result)
        
        if not result or "flights" not in result:
            return ["No flight data available for the specified route and dates."]

        all_flights = result["flights"]

        if not all_flights:
            return ["No flights found for the specified route and dates."]

        best_flights = []

        for flight in all_flights:
            if (flight['is_best']):
                best_flights.append(flight)
        
        if not best_flights:
            return ["No best flights found for the specified route and dates."]


        top_n_flights = best_flights[0: min(30, len(best_flights))]

        flight_info = []

        origin_airport = origin
        destination_airport = destination

        for flight in top_n_flights:
            flight_info.append(format_flight_info(flight, origin_airport, destination_airport))

        output = ["Here are the best flights for this route and time: "] + flight_info


        return output
    



    except httpx.RequestError:
        return ["Unable to connect to the flight search service. Please try again later."]
    
    except ValueError as e:
        return [f"Invalid data received: {str(e)}"]
    
    except Exception as e:
        return [f"An unexpected error occurred while searching for flights: {str(e)}"]
    


@mcp.tool()
async def get_time_filtered_flights(state: str, target_time_str: str, origin: str, destination: str, departure_date: str,
                      trip_type: str = "one-way", seat: str = "economy",
                      adults: int = 1, children: int = 0, infants_in_seat: int = 0, infants_on_lap: int = 0) -> list[str]:
   
    """ Get time-filtered flight information based on the user's preferences for before or after a certain time for a given origin, destination, and departure date. If the user wants to do a round-trip,
    you will need to make two one-way trip calls.

    Args:
        state (str): The state of the flight ("before" or "after" only). For before, we do before the target time. For after, we do on or after the target time. 
        target_time_str (str): The target time in HH:MM AM/PM format (ex: "7:00 PM").
        origin (str): The origin airport IATA code (ex: "ATL", "SCL", "JFK").
        destination (str): The destination airport IATA code (ex: "DTW", "ICN", "LIR").
        departure_date (str): The departure date in YYYY-MM-DD format.

        trip_type (str, optional): The type of trip ("one-way" or "round-trip" only). Defaults to "one-way".
        seat (str, optional): The type of seat ("economy", "premium-economy", "business", or "first" only). Defaults to "economy".
        adults (int, optional): The number of adults. Defaults to 1.
        children (int, optional): The number of children. Defaults to 0.
        infants_in_seat (int, optional): The number of infants in a seat. Defaults to 0.
        infants_lap (int, optional): The number of infants on a lap. Defaults to 0.

    Returns:
        list[str]: A list of flight information strings.
    """

    if (len(origin) != 3 or len(destination) != 3):
        return ["Origin and destination must be 3 characters."]
    
    if (len(departure_date) != 10 or departure_date[4] != '-' or departure_date[7] != '-'):
        return ["Departure date must be in YYYY-MM-DD format."]
    
    if (trip_type != "one-way" and trip_type != "round-trip"):
        return ["Trip type must be either 'one-way' or 'round-trip'."]
    
    if (seat != "economy" and seat != "premium-economy" and seat != "business" and seat != "first"):
        return ["Seat type must be either 'economy', 'premium-economy', 'business', or 'first'."]
    
    if (state != "before" and state != "after"):
        return ["State must be either 'before' or 'after'."]

    try:
        # Validate time format first

        try:
            target_time = datetime.strptime(target_time_str, '%I:%M %p').time()
        except ValueError:
            return ["Invalid time format. Please use HH:MM AM/PM format (e.g., '7:00 PM')."]


        # Make API call to Google Flights via fast-flights
        flight_data_input = [FlightData(date=departure_date, from_airport=origin, to_airport=destination)]

        passengers_input = Passengers(adults=adults, children=children, infants_in_seat=infants_in_seat, infants_on_lap=infants_on_lap)

        # Create filter first, then get flights
        filter = create_filter(
            flight_data=flight_data_input,
            trip=trip_type,
            seat=seat,
            passengers=passengers_input
        )
        
        result: Result = await asyncio.to_thread(get_flights_from_filter, filter, mode="local")
        
        result = asdict(result)
        
        if not result or "flights" not in result:
            return ["No flight data available for the specified route and dates."]


        all_flights = result["flights"]

        if not all_flights:
            return ["No flights found for the specified route and dates."]


        valid_flights = []
        
        for flight in all_flights:

            parts = flight['departure'].split(" ")
            time_str = parts[0] + " " + parts[1]

            flight_time = datetime.strptime(time_str, '%I:%M %p').time()

            if (state == "before"):
                if (flight_time < target_time):
                    valid_flights.append(flight)
            elif (state == "after"):
                if (flight_time >= target_time):
                    valid_flights.append(flight)

        if not valid_flights:
            return [f"No flights found {state} {target_time_str} for the specified route and dates."]


        top_n_flights = valid_flights[0: min(30, len(valid_flights))]

        flight_info = []

        origin_airport = origin
        destination_airport = destination

        for flight in top_n_flights:
            flight_info.append(format_flight_info(flight, origin_airport, destination_airport))

        context_str = f"Here are the time-filtered flights {('before' if state == 'before' else 'on or after')} {target_time_str}: "

        output = [context_str] + flight_info


        return output


    except httpx.RequestError:
        return ["Unable to connect to the flight search service. Please try again later."]
    
    except ValueError as e:
        return [f"Invalid data received: {str(e)}"]
    
    except Exception as e:
        return [f"An unexpected error occurred while searching for flights: {str(e)}"]
    






def main():
    """Main entry point for the Google Flights MCP Server"""
    mcp.run(transport='stdio')

if __name__ == "__main__":
    main()