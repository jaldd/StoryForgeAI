package ai.storyforge.infrastructure.persistence;

import ai.storyforge.domain.model.NovelProject;
import ai.storyforge.domain.model.vo.NovelProjectId;
import ai.storyforge.domain.repository.NovelProjectRepository;
import java.util.List;
import java.util.Optional;
import org.springframework.stereotype.Repository;

@Repository
public class NovelProjectRepositoryImpl implements NovelProjectRepository {

    private final JpaNovelProjectRepository jpaRepo;

    public NovelProjectRepositoryImpl(JpaNovelProjectRepository jpaRepo) {
        this.jpaRepo = jpaRepo;
    }

    @Override
    public NovelProject save(NovelProject project) {
        return jpaRepo.save(project);
    }

    @Override
    public Optional<NovelProject> findById(NovelProjectId projectId) {
        return jpaRepo.findById(projectId);
    }

    @Override
    public List<NovelProject> findAll() {
        return jpaRepo.findAll();
    }
}
