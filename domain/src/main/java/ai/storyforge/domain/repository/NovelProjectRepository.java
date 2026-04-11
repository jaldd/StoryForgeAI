package ai.storyforge.domain.repository;

import ai.storyforge.domain.model.NovelProject;
import ai.storyforge.domain.model.vo.NovelProjectId;
import java.util.Optional;

public interface NovelProjectRepository {
    NovelProject save(NovelProject project);
    Optional<NovelProject> findById(NovelProjectId projectId);
    java.util.List<NovelProject> findAll();
}
