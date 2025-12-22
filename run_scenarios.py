"""
Trade Platform API Test Scenarios
Run various order scenarios to test bugs and system behavior
"""

import requests
import json
import time
from datetime import datetime

BASE_URL = "http://localhost:8000"
ORDERS_ENDPOINT = f"{BASE_URL}/orders"

def print_separator(title=""):
    """Print a section separator"""
    print("\n" + "="*80)
    if title:
        print(f"  {title}")
        print("="*80)
    print()

def make_order(symbol, quantity, order_type, scenario_name=""):
    """Make an order and display the response"""
    if scenario_name:
        print(f"\n{'─'*80}")
        print(f"📋 {scenario_name}")
        print(f"{'─'*80}")
    
    payload = {
        "symbol": symbol,
        "quantity": quantity,
        "order_type": order_type
    }
    
    print(f"\n🔹 Request: {order_type} {quantity} {symbol}")
    print(f"   Payload: {json.dumps(payload)}")
    
    try:
        start_time = time.time()
        response = requests.post(ORDERS_ENDPOINT, json=payload, timeout=30)
        elapsed = int((time.time() - start_time) * 1000)
        
        print(f"\n✅ Response Status: {response.status_code}")
        print(f"⏱️  Total Time: {elapsed}ms")
        
        if response.status_code == 200:
            data = response.json()
            print(f"\n📊 Order ID: {data.get('order_id')}")
            print(f"   Status: {data.get('status')}")
            print(f"   Trace ID: {data.get('trace_id')}")
            print(f"   Latency: {data.get('latency_ms')}ms")
            print(f"   Message: {data.get('message')}")
            
            # Show performance breakdown
            if 'details' in data and 'performance' in data['details']:
                perf = data['details']['performance']
                print(f"\n⚡ Performance Breakdown:")
                if 'breakdown' in perf:
                    breakdown = perf['breakdown']
                    print(f"   Validation: {breakdown.get('validation_ms')}ms")
                    print(f"   Pricing: {breakdown.get('pricing_ms')}ms")
                    print(f"   Risk: {breakdown.get('risk_assessment_ms')}ms")
                    print(f"   Execution: {breakdown.get('execution_ms')}ms")
            
            # Show summary
            if 'details' in data and 'summary' in data['details']:
                summary = data['details']['summary']
                print(f"\n💰 Summary:")
                print(f"   Price: ${summary.get('price')}")
                print(f"   Total Cost: ${summary.get('total_cost'):.2f}")
                print(f"   Estimated PnL: ${summary.get('estimated_pnl')}")
                print(f"   Risk Level: {summary.get('risk_level')}")
        else:
            print(f"\n❌ Error Response:")
            print(json.dumps(response.json(), indent=2))
    
    except requests.exceptions.Timeout:
        print(f"\n⚠️  Request timed out after 30 seconds")
    except requests.exceptions.ConnectionError:
        print(f"\n❌ Connection error - is the service running?")
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
    
    print(f"\n{'─'*80}\n")
    time.sleep(1)  # Brief pause between requests


def scenario_1_large_sell_fee_bug():
    """Scenario 1: Large SELL orders have excessive fees"""
    print_separator("SCENARIO 1: Why are my large SELL orders so expensive?")
    
    print("Expected: SELL 100 should have ~0.5% commission")
    make_order("NVDA", 100, "SELL", "Normal SELL (100 shares)")
    
    print("\n" + "─"*80)
    print("Expected: SELL 250 should trigger 2% extra fee bug (total ~2.5%)")
    make_order("NVDA", 250, "SELL", "Large SELL (250 shares) - BUG TRIGGER")


def scenario_2_stale_price_bug():
    """Scenario 2: Order passed validation but failed execution"""
    print_separator("SCENARIO 2: Order passed validation but failed execution")
    
    print("Expected: Should pass validation but might fail execution due to price variance")
    make_order("AAPL", 2850, "BUY", "Large order near $500K limit - Stale price bug")


def scenario_3_performance_delay():
    """Scenario 3: Tech stock orders take 3 seconds longer"""
    print_separator("SCENARIO 3: Tech stock orders are slower")
    
    print("Expected: TSLA should complete in ~8 seconds")
    make_order("TSLA", 50, "BUY", "TSLA order (Automotive sector)")
    
    print("\n" + "─"*80)
    print("Expected: NVDA should take ~11 seconds (3s delay for tech stocks)")
    make_order("NVDA", 50, "BUY", "NVDA order (Tech sector) - 3s delay")


def scenario_4_off_by_one_bug():
    """Scenario 4: Risk score jumped by adding 1 share"""
    print_separator("SCENARIO 4: Risk score jumps with 1 additional share")
    
    print("Expected: quantity_risk = 5 points (quantity <= 100)")
    make_order("AAPL", 100, "BUY", "100 shares - quantity_risk: 5 points")
    
    print("\n" + "─"*80)
    print("Expected: quantity_risk = 10 points (quantity > 100) - Off-by-one bug!")
    make_order("AAPL", 101, "BUY", "101 shares - quantity_risk: 10 points (BUG)")


def scenario_5_quantity_normalization():
    """Scenario 5: Quantity normalization"""
    print_separator("SCENARIO 5: Why did my order get normalized?")
    
    print("Expected: 157 shares normalized to 150 (lot size = 10)")
    make_order("AAPL", 157, "BUY", "157 shares (normalized to 150)")


def scenario_6_pnl_calculation():
    """Scenario 6: PnL for SELL orders"""
    print_separator("SCENARIO 6: SELL order PnL calculation")
    
    print("Expected: Should show positive PnL when selling above cost basis")
    make_order("AAPL", 100, "SELL", "SELL AAPL - Check if PnL is positive")


def scenario_7_boundary_conditions():
    """Scenario 7: Test boundary conditions"""
    print_separator("SCENARIO 7: Boundary condition testing")
    
    print("Testing orders that might hit exact risk score thresholds (40.0, 70.0)")
    make_order("AAPL", 150, "BUY", "Order near boundary risk score")


def scenario_8_tech_sector_limit():
    """Scenario 8: Tech sector concentration"""
    print_separator("SCENARIO 8: Tech sector concentration check")
    
    print("Expected: Should trigger sector exposure check and 3s delay")
    make_order("NVDA", 500, "BUY", "Large tech stock order - Sector limits")


def scenario_9_price_variance():
    """Scenario 9: Price variance between validation and execution"""
    print_separator("SCENARIO 9: Cross-service timing/price variance")
    
    print("Running same order multiple times to see price variance...")
    for i in range(3):
        make_order("AAPL", 50, "BUY", f"Run #{i+1} - Check price variance")


def scenario_10_sell_commission_comparison():
    """Scenario 10: Compare SELL commission for different symbols"""
    print_separator("SCENARIO 10: SELL commission comparison")
    
    print("Expected: AAPL SELL should have normal ~0.5% commission")
    make_order("AAPL", 250, "SELL", "SELL 250 AAPL")
    
    print("\n" + "─"*80)
    print("Expected: TSLA SELL should trigger 2% extra fee bug (qty > 200)")
    make_order("TSLA", 250, "SELL", "SELL 250 TSLA - Fee bug")


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
