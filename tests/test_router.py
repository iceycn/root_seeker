from root_seeker.config import RepoConfig
from root_seeker.services.router import RepoCatalog, ServiceRouter


def test_router_explicit_mapping():
    catalog = RepoCatalog(
        repos=[
            RepoConfig(
                service_name="order-service",
                git_url="https://git.example.com/order.git",
                local_dir="/tmp/order",
                repo_aliases=["order"],
                language_hints=["python"],
            )
        ]
    )
    router = ServiceRouter(catalog)
    out = router.route("order-service")
    assert out and out[0].confidence == 1.0
