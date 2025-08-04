#!/usr/bin/env python3
"""
Test MCP client to submit requests to the flights MCP server
"""

import asyncio
import json
import sys
from datetime import datetime, timedelta

async def test_mcp_flight_request():
    """Test flight search from JFK to FCO using MCP protocol"""
    
    print("Testing MCP Flight Request: JFK → FCO")
    print("="*50)
    
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
    
    print(f"Searching for flights on: {tomorrow}")
    print(f"Route: JFK (New York) → FCO (Rome)")
    print(f"Passengers: 1 adult, Economy class")
    print(f"Requesting: 5 flights")
    print("\nStarting MCP server and performing handshake...")
    
    process = None
    try:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "flights.py",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd="."
        )
        
        async def send_message(writer, message):
            writer.write((json.dumps(message) + "\n").encode('utf-8'))
            await writer.drain()

        initialize_request = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "clientInfo": {"name": "test-client", "version": "1.0.0"}
            }
        }
        print("Sending initialize request...")
        await send_message(process.stdin, initialize_request)
        
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        print("Sending initialized notification...")
        await send_message(process.stdin, initialized_notification)

        tool_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "name": "get_general_flights_info",
                "arguments": {
                    "origin": "JFK", "destination": "FCO", "departure_date": tomorrow,
                    "trip_type": "one-way", "seat": "economy", "adults": 1, "n_flights": 5
                }
            }
        }
        print("Sending tool call request...")
        await send_message(process.stdin, tool_request)

        print("\nWaiting for responses...")
        
        tool_response_found = False
        
        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=90.0)
                if not line:
                    break
                
                response = json.loads(line.decode('utf-8').strip())
                print(f"\nReceived Response:\n{json.dumps(response, indent=2)}")

                if response.get("id") == 2: 
                    tool_response_found = True
                    if "result" in response and "content" in response["result"]:
                        flights = response["result"]["content"]
                        if isinstance(flights, list) and len(flights) > 0:
                            print(f"\nSUCCESS! Found {len(flights)} flight results:")
                            for j, flight in enumerate(flights, 1):
                                if isinstance(flight, dict) and 'text' in flight:
                                    print(f"  Flight {j}: {flight['text'][:150]}...")
                                else:
                                    print(f"  Flight {j}: {str(flight)[:150]}...")
                        else:
                            print("\nNo flights found in response.")
                    else:
                        print("\nError in tool response.")
                    break 
            
            except asyncio.TimeoutError:
                print("\nTimed out waiting for server response after 90 seconds.")
                break
        
        if not tool_response_found:
            print("\nDid not receive the final tool response.")

        print("\ngracefully shutting down the server...")
        shutdown_request = {"jsonrpc": "2.0", "id": 3, "method": "shutdown"}
        await send_message(process.stdin, shutdown_request)
        
        while True:
            try:
                line = await asyncio.wait_for(process.stdout.readline(), timeout=10.0)
                if not line:
                    break
                response = json.loads(line.decode('utf-8').strip())
                if response.get("id") == 3:
                    print("Shutdown acknowledged by server.")
                    break
            except asyncio.TimeoutError:
                print("Timed out waiting for shutdown response.")
                break

        exit_notification = {"jsonrpc": "2.0", "method": "exit"}
        await send_message(process.stdin, exit_notification)
        
        await asyncio.wait_for(process.wait(), timeout=10.0)
        print("Server process terminated.")

    except Exception as e:
        print(f"\nError during MCP request: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if process and process.returncode is None:
            print("Terminating process forcefully.")
            process.terminate()
            await process.wait()

async def test_simple_import():
    """Test direct function call without MCP protocol"""
    print("\n" + "="*50)
    print("Testing Direct Function Call (Fallback)")
    print("="*50)
    
    try:
        sys.path.insert(0, '.')
        from flights import get_general_flights_info
        
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        print(f"Searching for flights on: {tomorrow}")
        print(f"Route: JFK → FCO")
        print("Calling function directly...")
        
        result = await get_general_flights_info(
            origin="JFK",
            destination="FCO", 
            departure_date=tomorrow,
            trip_type="one-way",
            seat="economy",
            adults=1,
            n_flights=3
        )
        
        print(f"\nDirect Function Result:")
        if isinstance(result, list):
            print(f"Found {len(result)} results:")
            for i, flight in enumerate(result, 1):
                print(f"  Result {i}: {flight[:150]}...")
        else:
            print(f"Result: {result}")
            
    except Exception as e:
        print(f"\nError in direct function call: {e}")
        import traceback
        traceback.print_exc()

async def main():
    print("MCP Flights Server Test Client")
    print("Testing flight search: JFK → FCO")
    print("="*60)
    
    await test_mcp_flight_request()
    
    await test_simple_import()
    
    print("\n" + "="*60)
    print("Test completed!")

if __name__ == "__main__":
    asyncio.run(main())