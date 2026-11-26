"""演示数据：首次运行 ``--demo`` 时创建四类账号、一个已审核店铺与若干菜品。"""

from takeout.container import Container


DEMO_PASSWORD = "123456"


def seed_demo(container: Container) -> bool:
    """创建演示数据；数据库已有用户时不做任何修改。"""
    if container.users.list_users():
        return False

    auth = container.auth
    auth.register_admin("13800000000", DEMO_PASSWORD)
    auth.register_customer(
        "13800000001", DEMO_PASSWORD, "南京大学仙林校区 1 栋 101 室"
    )
    auth.register_merchant(
        "13800000002", DEMO_PASSWORD, "仙林小馆", "NJ-LIC-2026-0001"
    )
    auth.register_courier("13800000003", DEMO_PASSWORD)
    auth.register_merchant(
        "13800000004", DEMO_PASSWORD, "仙林面馆", "NJ-LIC-2026-0002"
    )

    admin_token = auth.login("13800000000", DEMO_PASSWORD)
    admin_session = admin_token.session
    pending = container.shop_service.list_pending(admin_session)
    if pending:
        container.shop_service.audit(
            admin_session, pending[0].shop_id, True, "证照齐全，审核通过"
        )

    merchant_token = auth.login("13800000002", DEMO_PASSWORD)
    merchant_session = merchant_token.session
    dishes = [
        ("宫保鸡丁", "热菜", "28.00", 20),
        ("鱼香肉丝", "热菜", "24.00", 15),
        ("麻婆豆腐", "热菜", "16.00", 10),
        ("米饭", "主食", "2.00", 100),
        ("可乐", "饮料", "4.00", 50),
        ("番茄鸡蛋面", "主食", "18.00", 8),
    ]
    for name, category, price, stock in dishes:
        container.dish_service.create(
            merchant_session, name, category, price, stock, publish=True
        )
    return True
