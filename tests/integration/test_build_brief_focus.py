from app.extensions import db
from app.models import utcnow
from app.services.export_service import compose_export_files
from app.services.simple_mode import create_simple_project


def test_simple_mode_exports_target_product_build_brief(app):
    with app.app_context():
        result = create_simple_project(
            name="Portfolio Website",
            build_type="Website",
            target_user="Independent photographers",
            desired_outcome="A responsive portfolio website that helps visitors browse work and send inquiries.",
            brief=(
                "Build a portfolio website with a gallery, project detail pages, about page, "
                "contact form, admin-editable project entries, and responsive image layouts."
            ),
        )
        db.session.commit()

        project = result["project"]
        files = compose_export_files(project, utcnow())
        brief = files["AI_BUILD_BRIEF.md"]

        assert "FULA_BUILD_SPEC.md" not in files
        assert "# AI Build Brief: Portfolio Website" in brief
        assert "**Build type:** Website" in brief
        assert "portfolio website" in brief.lower()
        assert "Independent photographers" in brief
        assert "UAX Studio itself" in brief
        assert "- Upload or paste source material." not in brief
