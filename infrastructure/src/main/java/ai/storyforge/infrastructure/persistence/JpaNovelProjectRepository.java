package ai.storyforge.infrastructure.persistence;

import ai.storyforge.domain.model.NovelProject;
import ai.storyforge.domain.model.vo.NovelProjectId;
import org.springframework.data.jpa.repository.JpaRepository;

interface JpaNovelProjectRepository extends JpaRepository<NovelProject, NovelProjectId> {
}
