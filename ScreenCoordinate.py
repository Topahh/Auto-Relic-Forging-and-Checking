"""
Filename: 屏幕坐标获取_ScreenRegion_优化版.py
Description: Screen Coordinate Acquisition Tool (屏幕坐标获取工具)
Version: 2.0
"""
import pyautogui
import time
import mss

def get_2k_coordinates():
    """生成2K分辨率默认坐标 / Generate default coordinates for 2K resolution"""
    print("\n=== 2K分辨率坐标数据 / 2K Resolution Coordinate Data ===")
    print("left = 835")
    print("top = 810")
    print("width = 1030")
    print("height = 310")

def get_4k_coordinates():
    """生成4K分辨率默认坐标 / Generate default coordinates for 4K resolution"""
    print("\n=== 4K分辨率坐标数据 / 4K Resolution Coordinate Data ===")
    print("left = 1250")
    print("top = 1205")
    print("width = 1500")
    print("height = 450")

def manual_acquisition():
    """手动获取屏幕坐标 / Manual screen coordinate acquisition"""
    print("\n=== 手动坐标获取模式 / Manual Coordinate Acquisition Mode ===")
    print("请在4秒内将鼠标移动到目标区域的【左上角】...")
    print("Please move the mouse to the [Top-Left Corner] of the target area within 4 seconds...")
    time.sleep(4)
    x1, y1 = pyautogui.position()
    print(f"左上角坐标 / Top-Left Corner: x={x1}, y={y1}")
    
    print("\n请在4秒内将鼠标移动到目标区域的【右下角】...")
    print("Please move the mouse to the [Bottom-Right Corner] of the target area within 4 seconds...")
    time.sleep(4)
    x2, y2 = pyautogui.position()
    print(f"右下角坐标 / Bottom-Right Corner: x={x2}, y={y2}")
    
    print(f"\n=== 坐标数据输出 / Coordinate Data Output ===")
    print(f"left = {x1}")
    print(f"top = {y1}")
    print(f"width = {x2-x1}")
    print(f"height = {y2-y1}")

def list_monitors():
    """Lister tous les moniteurs disponibles avec mss"""
    with mss.mss() as sct:
        print("\n=== Moniteurs détectés ===")
        # monitors[0] = écran virtuel combiné, monitors[1+] = écrans individuels
        for i, m in enumerate(sct.monitors):
            print(f"[{i}] left={m['left']}, top={m['top']}, "
                  f"width={m['width']}, height={m['height']}")

        choice = int(input("\nChoisir le numéro du moniteur : "))
        m = sct.monitors[choice]
        print(f"\nleft = {m['left']}\ntop = {m['top']}\n"
              f"width = {m['width']}\nheight = {m['height']}")

def main():
    """主程序 / Main Program"""
    print("="*60)
    print("屏幕坐标获取工具 / Screen Coordinate Acquisition Tool")
    print("="*60)
    print("\n请选择操作模式 / Please select operation mode:")
    print("1 - 生成2K分辨率默认坐标 / Generate 2K (2560x1440) default coordinates")
    print("2 - 生成4K分辨率默认坐标 / Generate 4K (3840x2160) default coordinates")
    print("3 - 手动获取坐标 / Manual coordinate acquisition")
    print("4 - 列出所有监视器并选择 / List all monitors and select")
    print("-"*60)
    
    choice = input("请输入选项 (1/2/3/4) / Enter option (1/2/3/4): ").strip()
    
    if choice == "1":
        get_2k_coordinates()
    elif choice == "2":
        get_4k_coordinates()
    elif choice == "3":
        manual_acquisition()
    elif choice == "4":
        list_monitors()
    else:
        print("\n无效输入,程序终止 / Invalid input, program terminated")
        return
    
    # 防止窗口自动关闭 / Prevent window from auto-closing
    input("\n程序执行完毕,按回车键退出... / Program completed, press Enter to exit...")

if __name__ == "__main__":
    main()
