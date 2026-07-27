const {test, expect} = require("../fixtures");

const USER_AGENTS = [
    {
        ua: "",
        browser_name: true,
        browser_version: true,
        os_name: true,
        is_safari: false,
        is_mac: false
    }, // default
    {
        ua: "Mozilla/5.0 (X11; Linux x86_64; rv:147.0) Gecko/20100101 Firefox/147.0",
        browser_name: "Firefox",
        browser_version: "147.0",
        os_name: "Linux",
        is_safari: false,
        is_mac: false
    },
    {
        ua: "Mozilla/5.0 (Macintosh; Intel Mac OS X 15_7_4) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/26.0 Safari/605.1.15",
        browser_name: "Safari",
        browser_version: "26.0",
        os_name: "Mac OS",
        is_safari: true,
        is_mac: true
    },
    {
        ua: "Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1",
        browser_name: "Mobile Safari",
        browser_version: "15.0",
        os_name: "iOS",
        is_safari: true,
        is_mac: false
    },
    {
        ua: "PrusaSlicer/2.9.4 (Windows)",
        browser_name: "PrusaSlicer",
        browser_version: "2.9.4",
        os_name: "Windows",
        is_safari: false,
        is_mac: false
    }, // see # 5235
    {
        ua: "PrusaSlicer/2.9.4 (Linux)",
        browser_name: "PrusaSlicer",
        browser_version: "2.9.4",
        os_name: "Linux",
        is_safari: false,
        is_mac: false
    }, // see # 5235
    {
        ua: "curl/1.2.3",
        browser_name: false,
        browser_version: false,
        os_name: false,
        is_safari: false,
        is_mac: false
    },
    {
        ua: "something weird",
        browser_name: false,
        browser_version: false,
        os_name: false,
        is_safari: false,
        is_mac: false
    }
];

const checkStringValue = (expected, actual) => {
    if (typeof expected == "boolean") {
        if (expected) {
            expect(actual).toBeTruthy();
        } else {
            expect(actual).toBe("unknown");
        }
    } else {
        expect(actual).toBe(expected);
    }
};

USER_AGENTS.forEach(({ua, browser_name, browser_version, os_name, is_safari, is_mac}) => {
    test.describe.parallel(`User Agent: ${ua ? ua : "default"}`, () => {
        test.use({userAgent: ua});

        test("error free page load", async ({page, ui}) => {
            const errors = [];
            page.on("pageerror", (error) => {
                errors.push(`[${error.name}] ${error.message}`);
            });
            page.on("console", (msg) => {
                if (msg.type() === "error") {
                    errors.push(`[${msg.type()}] ${msg.text()}`);
                }
            });

            await ui.gotoLoggedInCore();

            await expect(errors).toStrictEqual([]);
        });

        test("browser detection", async ({page, ui}) => {
            await ui.gotoLoggedInCore();

            const reportedBrowserInfo = await page.evaluate(() => {
                return window.OctoPrint.coreui.browser;
            });
            //console.log("Browser:", reportedBrowserInfo);

            checkStringValue(browser_name, reportedBrowserInfo.browser_name);
            checkStringValue(browser_version, reportedBrowserInfo.browser_version);
            checkStringValue(os_name, reportedBrowserInfo.os_name);

            expect(reportedBrowserInfo.safari).toBe(is_safari);
            expect(reportedBrowserInfo.is_mac).toBe(is_mac);

            if (is_safari) {
                await expect(page.locator("html")).toHaveClass(/(^|\s)safari(\s|$)/);
            } else {
                await expect(page.locator("html")).not.toHaveClass(/(^|\s)safari(\s|$)/);
            }

            if (is_mac) {
                await expect(page.locator("html")).toHaveClass(/(^|\s)macos(\s|$)/);
            } else {
                await expect(page.locator("html")).not.toHaveClass(/(^|\s)macos(\s|$)/);
            }
        });
    });
});
