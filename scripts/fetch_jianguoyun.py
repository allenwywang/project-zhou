"""
获取坚果云分享页内容
"""
from playwright.sync_api import sync_playwright
import time

def main():
    print("打开坚果云页面...")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.goto("https://www.jianguoyun.com/p/DcEaxJgQ-P7XCRiJnL4FIAA", timeout=30000)
        page.wait_for_load_state("networkidle")
        time.sleep(1)

        # 填密码
        pwd_input = page.query_selector('input#access-pwd')
        if pwd_input:
            print("找到密码框，填入0403...")
            pwd_input.fill("0403")
            time.sleep(0.5)
            # 点击确定按钮
            ok_btn = page.query_selector(".ok-button")
            if ok_btn:
                print("点击确定按钮...")
                ok_btn.click()
                time.sleep(3)

        print("等待文件列表呈现...")
        page.wait_for_load_state("networkidle")
        time.sleep(5)

        # 截图
        page.screenshot(path="../assets/jianguoyun.png", full_page=True)
        print("截图已保存")

        # 保存html
        with open("../data/jianguoyun_page.html", "w", encoding="utf-8") as f:
            f.write(page.content())
        print("页面已保存")

        print("\n检查是否还有密码框...")
        pwd_verify = page.query_selector("#pwd-verify-view")
        if pwd_verify:
            print("密码框仍然存在，可能验证失败")
        else:
            print("密码验证通过！")

        # 打印body关键内容
        file_list = page.query_selector(".file-list, .pub-file-list, #file-list")
        if file_list:
            print("\n找到文件列表区域")

        browser.close()

    print("完成")
    input("按Enter结束...")


if __name__ == "__main__":
    main()