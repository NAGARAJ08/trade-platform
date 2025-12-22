"""
Trade Platform API Test Scenarios
Run various order scenarios to test bugs and system behavior
"""


import requests
import json
import time
from datetime import datetime
import threading

# Log file path
LOG_FILE = "scenario_traceids.log"

def log_to_file(case_num, description, payload, trace_id):
    """Log scenario input and traceid to the log file"""
    with threading.Lock():
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"case {case_num}: {description}\n")
            f.write(f"input : {json.dumps(payload)}\n")
            f.write(f"traceid : {trace_id}\n\n")

BASE_URL = "http://localhost:8000"
ORDERS_ENDPOINT = f"{BASE_URL}/orders"

def print_separator(title=""):
    """Print a section separator"""
    print("\n" + "="*80)
    if title:
        print(f"  {title}")
        print("="*80)
    print()


def make_order(symbol, quantity, order_type, scenario_name="", case_num=None, description=None):
    """Make an order and log the response traceid"""
    payload = {
        "symbol": symbol,
        "quantity": quantity,
        "order_type": order_type
    }
    try:
        response = requests.post(ORDERS_ENDPOINT, json=payload, timeout=30)
        if response.status_code == 200:
            data = response.json()
            trace_id = data.get('trace_id', 'N/A')
            log_to_file(case_num or "?", description or scenario_name or "", payload, trace_id)
        else:
            log_to_file(case_num or "?", description or scenario_name or "", payload, f"ERROR: {response.status_code}")
    except requests.exceptions.Timeout:
        log_to_file(case_num or "?", description or scenario_name or "", payload, "TIMEOUT")
    except requests.exceptions.ConnectionError:
        log_to_file(case_num or "?", description or scenario_name or "", payload, "CONNECTION_ERROR")
    except Exception as e:
        log_to_file(case_num or "?", description or scenario_name or "", payload, f"ERROR: {str(e)}")
    time.sleep(1)  # Brief pause between requests


def scenario_1_large_sell_fee_bug():
    """Scenario 1: Large SELL orders have excessive fees"""
    make_order("NVDA", 100, "SELL", case_num="1", description="Normal SELL (100 shares) ~0.5% commission")
    make_order("NVDA", 250, "SELL", case_num="1", description="Large SELL (250 shares) - triggers 2% extra fee bug (~2.5%)")


def scenario_2_stale_price_bug():
    """Scenario 2: Order passed validation but failed execution"""
    make_order("AAPL", 2850, "BUY", case_num="2", description="Large order near $500K limit - Stale price bug")


def scenario_3_performance_delay():
    """Scenario 3: Tech stock orders take 3 seconds longer"""
    make_order("TSLA", 50, "BUY", case_num="3", description="TSLA order (Automotive sector) ~8s expected")
    make_order("NVDA", 50, "BUY", case_num="3", description="NVDA order (Tech sector) - 3s delay, ~11s expected")


def scenario_4_off_by_one_bug():
    """Scenario 4: Risk score jumped by adding 1 share"""
    make_order("AAPL", 100, "BUY", case_num="4", description="100 shares - quantity_risk: 5 points")
    make_order("AAPL", 101, "BUY", case_num="4", description="101 shares - quantity_risk: 10 points (BUG)")


def scenario_5_quantity_normalization():
    """Scenario 5: Quantity normalization"""
    make_order("AAPL", 157, "BUY", case_num="5", description="157 shares (normalized to 150)")


def scenario_6_pnl_calculation():
    """Scenario 6: PnL for SELL orders"""
    make_order("AAPL", 100, "SELL", case_num="6", description="SELL AAPL - Check if PnL is positive")


def scenario_7_boundary_conditions():
    """Scenario 7: Test boundary conditions"""
    make_order("AAPL", 150, "BUY", case_num="7", description="Order near boundary risk score (40.0, 70.0)")


def scenario_8_tech_sector_limit():
    """Scenario 8: Tech sector concentration"""
    make_order("NVDA", 500, "BUY", case_num="8", description="Large tech stock order - Sector limits, triggers 3s delay")


def scenario_9_price_variance():
    """Scenario 9: Price variance between validation and execution"""
    for i in range(3):
        make_order("AAPL", 50, "BUY", case_num="9", description=f"Run #{i+1} - Check price variance")


def scenario_10_sell_commission_comparison():
    """Scenario 10: Compare SELL commission for different symbols"""
    make_order("AAPL", 250, "SELL", case_num="10", description="SELL 250 AAPL - normal ~0.5% commission")
    make_order("TSLA", 250, "SELL", case_num="10", description="SELL 250 TSLA - triggers 2% extra fee bug (qty > 200)")


def run_all_scenarios():
    """Run all test scenarios"""
    print("\n" + "🚀 "*30)
    print("  TRADE PLATFORM API SCENARIOS")
    print("  Starting at:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("🚀 "*30)
    
    scenarios = [
        ("1", "Large SELL Fee Bug", scenario_1_large_sell_fee_bug),
        ("2", "Stale Price Bug", scenario_2_stale_price_bug),
        ("3", "Performance Delay", scenario_3_performance_delay),
        ("4", "Off-by-One Bug", scenario_4_off_by_one_bug),
        ("5", "Quantity Normalization", scenario_5_quantity_normalization),
        ("6", "PnL Calculation", scenario_6_pnl_calculation),
        ("7", "Boundary Conditions", scenario_7_boundary_conditions),
        ("8", "Tech Sector Limit", scenario_8_tech_sector_limit),
        ("9", "Price Variance", scenario_9_price_variance),
        ("10", "SELL Commission Comparison", scenario_10_sell_commission_comparison),
    ]
    
    for num, name, func in scenarios:
        try:
            func()
        except KeyboardInterrupt:
            print("\n\n⚠️  Interrupted by user")
            break
        except Exception as e:
            print(f"\n❌ Error in scenario {num}: {str(e)}")
            continue
    
    print("\n" + "🏁 "*30)
    print("  ALL SCENARIOS COMPLETED")
    print("  Finished at:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("🏁 "*30 + "\n")


def main():
    """Main entry point"""
    import sys
    
    if len(sys.argv) > 1:
        scenario = sys.argv[1]
        scenarios = {
            "1": scenario_1_large_sell_fee_bug,
            "2": scenario_2_stale_price_bug,
            "3": scenario_3_performance_delay,
            "4": scenario_4_off_by_one_bug,
            "5": scenario_5_quantity_normalization,
            "6": scenario_6_pnl_calculation,
            "7": scenario_7_boundary_conditions,
            "8": scenario_8_tech_sector_limit,
            "9": scenario_9_price_variance,
            "10": scenario_10_sell_commission_comparison,
            "all": run_all_scenarios,
        }
        
        if scenario in scenarios:
            scenarios[scenario]()
        else:
            print(f"❌ Unknown scenario: {scenario}")
            print(f"Available: {', '.join(scenarios.keys())}")
    else:
        # Interactive menu
        print("\n" + "="*80)
        print("  TRADE PLATFORM API SCENARIOS")
        print("="*80)
        print("\nAvailable scenarios:")
        print("  1  - Large SELL Fee Bug")
        print("  2  - Stale Price Bug")
        print("  3  - Performance Delay (Tech vs Non-Tech)")
        print("  4  - Off-by-One Bug (100 vs 101 shares)")
        print("  5  - Quantity Normalization")
        print("  6  - PnL Calculation")
        print("  7  - Boundary Conditions")
        print("  8  - Tech Sector Limit")
        print("  9  - Price Variance")
        print("  10 - SELL Commission Comparison")
        print("  all - Run all scenarios")
        print("  q  - Quit")
        print("\nUsage: python run_scenarios.py [scenario_number]")
        print("Example: python run_scenarios.py 1")
        print("Example: python run_scenarios.py all\n")
        
        choice = input("Enter scenario number (or 'all'): ").strip()
        
        scenarios = {
            "1": scenario_1_large_sell_fee_bug,
            "2": scenario_2_stale_price_bug,
            "3": scenario_3_performance_delay,
            "4": scenario_4_off_by_one_bug,
            "5": scenario_5_quantity_normalization,
            "6": scenario_6_pnl_calculation,
            "7": scenario_7_boundary_conditions,
            "8": scenario_8_tech_sector_limit,
            "9": scenario_9_price_variance,
            "10": scenario_10_sell_commission_comparison,
            "all": run_all_scenarios,
        }
        
        if choice in scenarios:
            scenarios[choice]()
        elif choice.lower() != 'q':
            print(f"❌ Invalid choice: {choice}")


if __name__ == "__main__":
    main()
