"""Class creation (D5), people management, join codes (D4), teacher detection."""

from __future__ import annotations


def test_teaching_summary_drives_the_persona(student_client, ta_client, instructor_client, course):
    student = student_client.get("/api/v1/me").json()["teaching"]
    assert student == {"is_teacher": False, "staff_course_count": 0,
                       "student_course_count": 1, "can_create_courses": False}
    # The seeded TA has global role "student": course role must still count.
    ta = ta_client.get("/api/v1/me").json()["teaching"]
    assert ta["is_teacher"] is True and ta["staff_course_count"] == 1
    assert ta["can_create_courses"] is False
    instructor = instructor_client.get("/api/v1/me").json()["teaching"]
    assert instructor["is_teacher"] is True and instructor["can_create_courses"] is True


def test_login_response_includes_teaching(client, users, course):
    response = client.post(
        "/api/v1/auth/login", json={"email": "ta@test.local", "password": "test-password"}
    )
    assert response.json()["user"]["teaching"]["is_teacher"] is True


def test_instructor_creates_class_and_becomes_its_instructor(instructor_client, student_client, users):
    created = instructor_client.post(
        "/api/v1/courses",
        json={"name": "Data Wrangling", "code": "dw-201", "term": "2027-S1"},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["code"] == "DW-201" and body["role_in_course"] == "instructor"
    duplicate = instructor_client.post(
        "/api/v1/courses", json={"name": "Again", "code": "DW-201", "term": "x"}
    )
    assert duplicate.status_code == 409
    assert student_client.post(
        "/api/v1/courses", json={"name": "Mine", "code": "S-1", "term": "x"}
    ).status_code == 403


def test_members_add_remove_and_last_instructor_guard(instructor_client, ta_client, course, users):
    members = instructor_client.get(f"/api/v1/courses/{course.id}/members").json()["members"]
    assert [m["role_in_course"] for m in members] == ["instructor", "ta", "student", "student"]
    assert ta_client.get(f"/api/v1/courses/{course.id}/members").status_code == 200

    added = instructor_client.post(
        f"/api/v1/courses/{course.id}/members",
        json={"emails": ["STUDENT1@test.local", "ghost@test.local", "ta@test.local"], "role_in_course": "ta"},
    ).json()
    assert [m["email"] for m in added["updated"]] == ["student1@test.local"]
    assert added["unknown"] == ["ghost@test.local"]
    assert added["added"] == []
    # TAs cannot manage people.
    assert ta_client.post(
        f"/api/v1/courses/{course.id}/members", json={"emails": ["x@test.local"]}
    ).status_code == 403

    instructor_id = users["instructor@test.local"].id
    demote = instructor_client.patch(
        f"/api/v1/courses/{course.id}/enrollments/{instructor_id}", json={"role_in_course": "ta"}
    )
    assert demote.status_code == 409 and demote.json()["error"]["code"] == "LAST_INSTRUCTOR"
    remove_self = instructor_client.delete(f"/api/v1/courses/{course.id}/enrollments/{instructor_id}")
    assert remove_self.status_code == 409

    student2 = users["student2@test.local"].id
    assert instructor_client.delete(f"/api/v1/courses/{course.id}/enrollments/{student2}").status_code == 204
    remaining = {m["email"] for m in instructor_client.get(f"/api/v1/courses/{course.id}/members").json()["members"]}
    assert "student2@test.local" not in remaining


def test_join_code_lifecycle(instructor_client, student_client, other_student_client, course, users, db):
    from sqlalchemy import delete

    from app.courses.models import Enrollment

    # student2 leaves so they can rejoin with a code.
    db.execute(delete(Enrollment).where(Enrollment.user_id == users["student2@test.local"].id))
    db.commit()
    assert other_student_client.get(f"/api/v1/courses/{course.id}").status_code == 404

    code = instructor_client.post(f"/api/v1/courses/{course.id}/join-code").json()["join_code"]
    assert code and len(code) == 7
    # Only instructors see the code.
    assert student_client.get(f"/api/v1/courses/{course.id}").json()["join_code"] is None
    joined = other_student_client.post("/api/v1/courses/join", json={"code": code.lower()})
    assert joined.status_code == 200 and joined.json()["role_in_course"] == "student"
    # Joining twice is harmless and never changes an existing role.
    assert instructor_client.post("/api/v1/courses/join", json={"code": code}).json()["role_in_course"] == "instructor"

    instructor_client.delete(f"/api/v1/courses/{course.id}/join-code")
    assert other_student_client.post("/api/v1/courses/join", json={"code": code}).status_code == 404
    rotated = instructor_client.post(f"/api/v1/courses/{course.id}/join-code").json()["join_code"]
    assert rotated != code
    instructor_client.patch(f"/api/v1/courses/{course.id}", json={"status": "archived"})
    assert other_student_client.post("/api/v1/courses/join", json={"code": rotated}).status_code == 404
